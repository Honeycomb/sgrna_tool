#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
annot_variants.py generates a dataframe that stores annotations for each variant in 
the specified locus and genome that tell us whether the variant generates allele-specific 
sgRNA sites for the Cas variety/varieties specified. Written in Python v 3.6.1.
Kathleen Keough et al. 2018.
Usage:
    annot_variants.py [-v] <gens_file> <cas> <pams_dir> <ref_genome_fasta> <out> [--guide_len=<S>]
    annot_variants.py -C | --cas-list

Arguments:
    gens_file           Explicit genotypes file generated by get_gens_df.py
    cas                 Types of cas, comma-separated.
    pams_dir            Directory where pam locations in ref_genome are located. 
    ref_genome_fasta    Fasta file for reference genome.
    out                 Prefix for output files.
Options:
    -C --cas-list       List available cas types and exits.
    -v                  Verbose mode.
    --guide_len=<S>     Guide length, commonly 20 bp, for annotating guides near a PAM [default: 20].
"""

import pandas as pd
import numpy as np
from docopt import docopt
import os, sys, logging
from collections import Counter
from pyfaidx import Fasta
import regex

__version__ = "1.0.0"

# 3 and 5 prime cas lists

# Get apsolute path for gen_targ_dfs.py, and edit it for cas_object.py
ef_path = os.path.dirname(os.path.realpath(__file__))
cas_obj_path = ef_path.replace("preprocessing/annotate_variants", "scripts/")
sys.path.append(cas_obj_path)

metadata_path = ef_path.replace("annotate_variants", "")
sys.path.append(metadata_path)
# Import cas_object
import cas_object as cas_obj
from get_metadata import add_metadata


def norm_chr(chrom_str, gens_chrom):
    """
    Returns the chromosome string that matches the chromosome annotation of the input gens file
    """
    chrom_str = str(chrom_str)
    if not gens_chrom:
        return chrom_str.replace("chr", "")
    elif gens_chrom and not chrom_str.startswith("chr"):
        return "chr" + chrom_str
    else:
        return chrom_str


def get_range_upstream(pam_pos, guide_len):
    """
    Get positions N bp upstream, i.e. for forward 3' PAMs or reverse 5' PAMs
    :param pam_pos: position of PAM, int.
    :return: sgRNA seed region positions, set of ints.
    """
    sgrna = set(range(pam_pos - guide_len, pam_pos))
    return sgrna


def get_range_downstream(pam_pos, guide_len):
    """
    Get positions N bp downstream, i.e. for forward 5' PAMs or reverse 3' PAMs
    :param pam_pos: position of PAM, int.
    :return: sgRNA seed region positions, set of ints.
    """
    sgrna = set(range(pam_pos + 1, pam_pos + (guide_len + 1)))
    return sgrna


def find_spec_pams(cas_obj, python_string, orient="3prime"):
    # orient specifies whether this is a 3prime PAM (e.g. Cas9, PAM seq 3' of sgRNA)
    # or a 5prime PAM (e.g. cpf1, PAM 5' of sgRNA)

    # get sequence

    sequence = python_string

    # get PAM sites (the five prime three prime thing will need to be reversed for cpf1)

    def get_pam_fiveprime(pam_regex, sequence):
        starts = set()
        for pam in regex.finditer(
            pam_regex, sequence, regex.IGNORECASE, overlapped=True
        ):
            starts.add(pam.start() + 1)
        return set(starts)

    def get_pam_threeprime(pam_regex, sequence):
        starts = set()
        for pam in regex.finditer(
            pam_regex, sequence, regex.IGNORECASE, overlapped=True
        ):
            starts.add(pam.end())
        return set(starts)

    if orient == "3prime":
        for_starts = get_pam_fiveprime(cas_obj.forwardPam_regex(), sequence)
        rev_starts = get_pam_threeprime(cas_obj.reversePam_regex(), sequence)
    elif orient == "5prime":
        for_starts = get_pam_threeprime(cas_obj.forwardPam_regex(), sequence)
        rev_starts = get_pam_fiveprime(cas_obj.reversePam_regex(), sequence)

    return (for_starts, rev_starts)


def makes_breaks_pam(cas_obj, chrom, pos, ref, alt, ref_genome):

    """
    Determine if cas in question makes or breaks PAM sites.
    :param chrom: chromosome, int.
    :param pos: position, int.
    :param ref: ref genotype, str.
    :param alt: alt genotype, str.
    :param ref_genome: ref_genome fasta file, fasta.
    :return:
    """
    makes_pam = False
    breaks_pam = False

    var = pos

    if "<" in alt:
        return makes_pam, breaks_pam

    # if alt is not a special case (CNV or SV), continue checking the new sequence

    ref_seq = ref_genome[str(chrom)][pos - 11 : pos + 10]

    if len(ref) > len(alt):  # handles deletions
        alt_seq = (
            ref_genome[str(chrom)][var - 11 : var - 1]
            + alt
            + ref_genome[str(chrom)][
                var + len(ref) + len(alt) - 2 : var + len(ref) + len(alt) - 2 + 10
            ]
        )
    else:
        alt_seq = (
            ref_genome[str(chrom)][var - 11 : var - 1]
            + alt
            + ref_genome[str(chrom)][var + len(alt) - 1 : var + len(alt) - 1 + 10]
        )

    if cas_obj.primeness == "5'":
        ref_pams_for, ref_pams_rev = find_spec_pams(cas_obj, ref_seq, orient="5prime")
        alt_pams_for, alt_pams_rev = find_spec_pams(cas_obj, alt_seq, orient="5prime")
    else:
        ref_pams_for, ref_pams_rev = find_spec_pams(cas_obj, ref_seq)
        alt_pams_for, alt_pams_rev = find_spec_pams(cas_obj, alt_seq)

    if (
        len(alt_pams_for) - len(ref_pams_for) > 0
        or len(alt_pams_rev) - len(ref_pams_rev) > 0
    ):
        makes_pam = True
    elif (
        len(ref_pams_for) - len(alt_pams_for) > 0
        or len(ref_pams_rev) - len(alt_pams_rev) > 0
    ):
        breaks_pam = True

    return makes_pam, breaks_pam


def get_made_broke_pams(df, chrom, ref_genome):

    """
    Apply makes_breaks_pams to a df.
    :param df: gens df generated by get_chr_tables.sh, available on EF github.
    :param chrom: chromosome currently being analyzed.
    :param ref_genome: ref_genome fasta, pyfaidx format.
    :return: dataframe with indicators for whether each variant makes/breaks PAMs, pd df.
    """
    FULL_CAS_LIST = cas_obj.get_cas_list(os.path.join(cas_obj_path, "CAS_LIST.txt"))
    for cas in cas_list:
        if cas not in FULL_CAS_LIST:
            logging.info(f"Skipping {cas}, not in CAS_LIST.txt")
            continue
        current_cas = cas_obj.get_cas_enzyme(
            cas, os.path.join(cas_obj_path, "CAS_LIST.txt")
        )

        makes, breaks = zip(
            *df.apply(
                lambda row: makes_breaks_pam(
                    current_cas, chrom, row["pos"], row["ref"], row["alt"], ref_genome
                ),
                axis=1,
            )
        )
        df[f"makes_{cas}"] = makes
        df[f"breaks_{cas}"] = breaks
    return df


def split_gens(gens_df, chroms):
    """
    Takes in a gens file with multiple loci, and splits it based on chromosome.
    :param gens_df: gens dataframe.
    :param chroms: list of chromosome notations.
    :return: list of dataframse, each dataframe with one chromosome notation at the CHROM column.
    """
    return [gens_df.loc[gens_df["chrom"] == c] for c in chroms]


def main(args):
    logging.info(args)
    out = args["<out>"]
    pams_dir = args["<pams_dir>"]
    gens = args["<gens_file>"]
    guide_len = int(args["--guide_len"])
    ref_genome = Fasta(args["<ref_genome_fasta>"], as_raw=True)

    global cas_list
    cas_list = list(args["<cas>"].split(","))

    # Read in gens and chroms file, and see if gens file needs to be split.
    gens = pd.read_hdf(gens, "all")
    if gens.empty:
        print('No variants in this region.')
        exit()
    chroms = dict(Counter(gens.chrom)).keys()

    if len(chroms) > 1:
        gens = split_gens(gens, list(chroms))
    else:
        gens = [gens]

    fasta_chrom = list(ref_genome.keys())[0].startswith("chr")
    chroms = [norm_chr(ch, fasta_chrom) for ch in list(chroms)]

    # # Add check to make sure the correct FASTA file was loaded. - this is too glitchy
    # if set(chroms) != set(list(ref_genome.keys())):
    #     logging.error(f"{args['<gens_file>']} chromosomes/notations differ from {args['<ref_genome_fasta>']}: {chroms} and {list(ref_genome.keys())}.")
    #     exit(1)

    # save locations of PAM proximal variants to dictionary
    pam_prox_vars = {}
    # get variants within sgRNA region for 3 prime PAMs (20 bp upstream of for pos and vice versa)
    FULL_CAS_LIST = cas_obj.get_cas_list(os.path.join(cas_obj_path, "CAS_LIST.txt"))
    for cas in cas_list:
        if cas not in FULL_CAS_LIST:
            logging.info(f"Skipping {cas}, not in CAS_LIST.txt")
            cas_list.remove(cas)

    combined_df = []
    for i, chrom in enumerate(chroms):
        chr_variants = set(gens[i]["pos"].tolist())
        for cas in cas_list:
            current_cas = cas_obj.get_cas_enzyme(
                cas, os.path.join(cas_obj_path, "CAS_LIST.txt")
            )

            logging.info(f"Evaluating {current_cas.name} at {chrom}.")
            cas_prox_vars = []
            pam_dict = {}
            pam_for_pos = np.load(
                os.path.join(pams_dir, f"{chrom}_{cas}_pam_sites_for.npy")
            ).tolist()
            pam_rev_pos = np.load(
                os.path.join(pams_dir, f"{chrom}_{cas}_pam_sites_rev.npy")
            ).tolist()

            if current_cas.primeness == "3'":
                for pos in pam_for_pos:
                    prox_vars = set(get_range_upstream(pos, guide_len)) & chr_variants
                    cas_prox_vars.extend(prox_vars)
                    pam_dict[pos] = prox_vars
                for pos in pam_rev_pos:
                    prox_vars = set(get_range_downstream(pos, guide_len)) & chr_variants
                    cas_prox_vars.extend(prox_vars)
                    pam_dict[pos] = prox_vars

            elif current_cas.primeness == "5'":
                for pos in pam_for_pos:
                    prox_vars = set(get_range_downstream(pos, guide_len)) & chr_variants
                    cas_prox_vars.extend(prox_vars)
                    pam_dict[pos] = prox_vars
                for pos in pam_rev_pos:
                    prox_vars = set(get_range_upstream(pos, guide_len)) & chr_variants
                    cas_prox_vars.extend(prox_vars)
                    pam_dict[pos] = prox_vars

            pam_prox_vars[cas] = cas_prox_vars

        chrdf = get_made_broke_pams(gens[i], chrom, ref_genome)

        for cas in cas_list:
            # print(cas)
            spec_pam_prox_vars = pam_prox_vars[cas]
            chrdf[f"var_near_{cas}"] = chrdf["pos"].isin(spec_pam_prox_vars)

        cas_cols = []
        for cas in cas_list:
            prelim_cols = [
                w.replace("cas", cas)
                for w in ["makes_cas", "breaks_cas", "var_near_cas"]
            ]
            cas_cols.extend(prelim_cols)
        keepcols = ["chrom", "pos", "ref", "alt"] + cas_cols
        chrdf = chrdf[keepcols]
        combined_df.append(chrdf)

    combined_df = pd.concat(combined_df)
    combined_df.to_hdf(
        f"{out}.h5",
        "all",
        mode="w",
        format="table",
        data_columns=True,
        complib="blosc",
    )

    add_metadata(
        f"{out}.h5", args, os.path.basename(__file__), __version__, "Annotation"
    )
    logging.info("Done.")


if __name__ == "__main__":
    arguments = docopt(__doc__, version=__version__)
    if arguments["--cas-list"]:
        cas_obj.print_cas_types()
        exit()
    if arguments["-v"]:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(asctime)s %(name)s:%(levelname)s ]%(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.ERROR,
            format="[%(asctime)s %(name)s:%(levelname)s ]%(message)s",
        )
    main(arguments)
