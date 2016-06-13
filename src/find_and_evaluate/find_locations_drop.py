#!/usr/bin/env python3

import pickle
import argparse
import collections
import time
import src.data_processing.util as util
from multiprocessing import Process
import logging
import pprint


def __create_parser_arguments(parser):
    """Creates the arguments for the parser"""
    parser.add_argument('doaminfilename_proto', type=str,
                        help='The path to the files with {} instead of the filenumber'
                             ' in the name so it is possible to format the string')
    parser.add_argument('trie_file', type=str,
                        help='The path to the pickle file with the trie from the'
                             'create_trie script')
    parser.add_argument('drop_rules_file', type=str,
                        help='The path to the json file with the drop rules from the'
                             'preprocess_drop_rules script')
    parser.add_argument('-n', '--file-count', type=int, default=8,
                        dest='fileCount',
                        help='number of files from preprocessing')
    parser.add_argument('-a', '--amount-dns-entries', type=int, default=0,
                        dest='amount',
                        help='Specify the amount of dns entries which should be searched'
                             ' per Process. Default is 0 which means all dns entries')
    parser.add_argument('-l', '--logging-file', type=str, default='find_drop.log', dest='log_file',
                        help='Specify a logging file where the log should be saved')
    # parser.add_argument('-r', '--profile', help='Profiles process 1 and 7',
    #                     dest='profile', action='store_true')


def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    __create_parser_arguments(parser)
    args = parser.parse_args()

    logging.basicConfig(filename=args.log_file, level=logging.DEBUG)

    with open(args.trie_file, 'rb') as trie_file:
        trie = pickle.load(trie_file)

    with open(args.drop_rules_file) as drop_rules_file:
        drop_rules = util.json_load(drop_rules_file)

    processes = []
    for index in range(0, args.fileCount):
        process = Process(target=start_search_in_file,
                          args=(args.doaminfilename_proto, index, trie,
                                drop_rules, args.amount),
                          kwargs={'amount': args.amount})
        processes.append(process)

    for process in processes:
        process.start()

    for process in processes:
        process.join()


def start_search_in_file(domainfile_proto: str, index: int, trie, drop_rules: [util.DRoPRule],
                         amount: int):
    """Start searching in file and timer to know the elapsed time"""
    start_time = time.time()
    search_in_file(domainfile_proto, index, trie, drop_rules, amount)

    end_time = time.time()
    logging.info('index {0}: search_in_file running time: {1}'
                 .format(index, (end_time - start_time)))


def search_in_file(domainfile_proto: str, index: int, trie, drop_rules: [util.DRoPRule],
                   amount: int):
    """Search in file"""
    match_count = collections.defaultdict(int)
    entries_stats = {'count': 0, 'loc_found_count': 0, 'length': 0}
    filename = domainfile_proto.format(index)
    with open(filename) as domain_file, open('.'.join(
            filename.split('.')[:-1]) + '_found.json', 'w') as loc_found_file, open(
                '.'.join(filename.split('.')[:-1]) + '_not_found.json', 'w') as no_loc_found_file:
        domains_w_location = []
        domains_wo_location = []

        def save_domain_with_location(loc_domain):
            domains_w_location.append(loc_domain)
            if len(domains_w_location) >= 10**4:
                util.json_dump(domains_w_location, loc_found_file)
                loc_found_file.write('\n')
                del domains_w_location[:]

        def save_domain_wo_location(loc_domain):
            domains_wo_location.append(loc_domain)
            if len(domains_wo_location) >= 10 ** 4:
                util.json_dump(domains_wo_location, no_loc_found_file)
                no_loc_found_file.write('\n')
                del domains_wo_location[:]

        for line in domain_file:
            amount -= 1
            domains = util.json_loads(line)
            for domain in domains:
                entries_stats['count'] += 1
                entries_stats['length'] += len(domain.domain_name)
                matches = []
                for rule in drop_rules:
                    for regex, code_type in rule.regex_pattern_rules:
                        match = regex.search(domain.domain_name)
                        if match:
                            entries_stats['loc_found_count'] += 1
                            matched_str = match.group('type')
                            locations = [loc for loc in trie.get(matched_str, [])
                                         if loc[1] == code_type.value]
                            for location in locations:
                                match_count[code_type.name] += 1
                                matches.append(util.DomainMatch(location[0], code_type,
                                                                matched_str, domain))
                domain.matches = matches
                if matches:
                    save_domain_with_location(domain)
                else:
                    save_domain_wo_location(domain)

            if amount == 0:
                break

        util.json_dump(domains_w_location, loc_found_file)
        util.json_dump(domains_wo_location, no_loc_found_file)

        logging.info('entries stats {}'.format(pprint.pformat(entries_stats, indent=4)))
        logging.info('matching stats {}'.format(pprint.pformat(match_count, indent=4)))

if __name__ == '__main__':
    main()
