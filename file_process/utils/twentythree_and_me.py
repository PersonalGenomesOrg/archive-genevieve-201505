"""23andme genotyping data extraction."""
from datetime import date, datetime
import json
import os
import re
from subprocess import check_output
from tempfile import TemporaryFile

import requests


SNP_DATA_23ANDME_FILE = os.path.join(
    os.path.dirname(__file__),
    '23andme_API_snps_data_with_ref_sorted.txt')

# Was used to generate reference genotypes in the previous file.
REFERENCE_GENOME_URL = ("http://hgdownload-test.cse.ucsc.edu/" +
                        "goldenPath/hg19/bigZips/hg19.2bit")

API23ANDME_Y_REGIONS_JSON = os.path.join(os.path.dirname(__file__),
                                         '23andme_y_chrom_regions.json')

VCF_FIELDS = ['CHROM', 'POS', 'ID', 'REF', 'ALT', 'QUAL', 'FILTER',
              'INFO', 'FORMAT', '23ANDME_DATA']


def snp_data_23andme():
    """Generator, returns SNP info sorted by chrom and position."""
    snp_data_file = open(SNP_DATA_23ANDME_FILE)
    next_line = snp_data_file.next()
    while next_line.startswith('#'):
        next_line = snp_data_file.next()
    expected_header = ['index', 'snp', 'chromosome',
                       'chromosome_position', 'reference_allele']
    assert next_line == '\t'.join(expected_header) + '\n'
    for line in snp_data_file:
        data = line.rstrip('\n').split('\t')
        yield data


def api23andme_full_gen_data(access_token, profile_id):
    """Get full genotype data from 23andme API."""
    headers = {'Authorization': 'Bearer %s' % access_token}
    genome_data_url = "http://api.23andme.com/1/genomes/%s" % profile_id
    genome_data_response = requests.get(genome_data_url, headers=headers)
    genome_data = genome_data_response.json()['genome']
    return genome_data


def api23andme_full_gen_infer_sex(genetic_data):
    """Check some known Y genotype calls to infer sex."""
    y_regions = json.load(open(API23ANDME_Y_REGIONS_JSON))
    y_seqs = ''.join([genetic_data[x[0]*2:x[0]*2+x[1]*2] for x in y_regions])
    if re.search(r'[ACGT]', y_seqs):
        return "Male"
    else:
        return "Female"


def vcf_header(source=None, reference=None, format_info=None):
    """Generate a VCF header."""
    header = []
    header.append("##fileformat=VCFv4.1")
    header.append("##fileDate=%s%s%s" %
                  (str(date.today().year),
                   str(date.today().month).zfill(2),
                   str(date.today().day).zfill(2)))
    if source:
        header.append("##source=" + source)
    if reference:
        header.append("##reference=%s" % reference)
    for item in format_info:
        header.append("##FORMAT=" + item)
    header.append('#' + '\t'.join(VCF_FIELDS))
    return header


def get_genotype(genetic_data, snp_info, sex):
    """Get genotype, collapsing hemizygous locations."""
    raw_genotype = genetic_data[int(snp_info[0])*2:int(snp_info[0])*2+2]
    if snp_info[2] in ['MT', 'M', 'Y', 'chrM', 'chrMT', 'chrY']:
        try:
            assert raw_genotype[0] == raw_genotype[1]
        except AssertionError:
            print raw_genotype
            print snp_info
            print sex
            raise SystemError
        return raw_genotype[0]
    if sex == 'Male' and snp_info[2] in ['X', 'chrX']:
        # PAR X coordinates for hg19 according to UCSC are:
        # chrX:60001-2699520 and chrX:154931044-155260560
        if (60001 <= int(snp_info[3]) <= 2699520 or
           154931044 <= int(snp_info[3]) <= 155260560):
            return raw_genotype
        else:
            try:
                assert raw_genotype[0] == raw_genotype[1]
            except AssertionError:
                print raw_genotype
                print snp_info
                print sex
                raise SystemError
            return raw_genotype[0]
    return raw_genotype


def api23andme_to_vcf_rows(genetic_data, sex):
    """Convert 23andme locations to unsorted VCF lines."""
    snp_info_data = snp_data_23andme()
    for snp_info in snp_info_data:
        genotype = get_genotype(genetic_data, snp_info, sex)
        if snp_info[4] == '_' or genotype == '__' or genotype == '--':
            continue
        if not re.match(r'^[ACGT]{1,2}$', genotype):
            continue
        vcf_data = {x: '.' for x in VCF_FIELDS}
        vcf_data['CHROM'] = snp_info[2]
        vcf_data['POS'] = snp_info[3]
        if snp_info[1].startswith('rs'):
            vcf_data['ID'] = snp_info[1]
        vcf_data['REF'] = snp_info[4]
        alt_alleles = []
        for alle in genotype:
            if not alle == vcf_data['REF'] and alle not in alt_alleles:
                alt_alleles.append(alle)
        if alt_alleles:
            vcf_data['ALT'] = ','.join(alt_alleles)
        vcf_data['FORMAT'] = 'GT'
        all_alleles = [vcf_data['REF']] + alt_alleles
        genotype_indexed = '/'.join([str(all_alleles.index(x)) for
                                     x in genotype])
        vcf_data['23ANDME_DATA'] = genotype_indexed
        yield '\t'.join([vcf_data[x] for x in VCF_FIELDS])


def api23andme_to_vcf(genetic_data, sex):
    """Create VCF file from 23andmeAPI full genotyping data"""
    print "Creating VCF data"
    commit = check_output(["git", "rev-parse", "HEAD"]).rstrip('\n')
    source = ("open_humans_data_extraction.twenty_three_and_me," +
              "commit:%s" % commit)
    reference = REFERENCE_GENOME_URL
    format_info = ['<ID=GT,Number=1,Type=String,Description="Genotype">']
    vcf_header_lines = vcf_header(source=source,
                                  reference=reference,
                                  format_info=format_info)
    for line in vcf_header_lines:
        yield line + '\n'
    vcf_rows = api23andme_to_vcf_rows(genetic_data, sex)
    for line in vcf_rows:
        yield line + '\n'
