#!/usr/bin/env python3

import argparse
import yaml
import src.data_processing.util as util
import logging


def __create_parser_arguments(parser):
    """Creates the arguments for the parser"""
    parser.add_argument('drop_rules_file_path', type=str,
                        help='The path to the file containing the drop rules')
    parser.add_argument('output_filename', type=str, default='drop_rules.json',
                        help='The path and name for the outputfile')
    parser.add_argument('-l', '--logging-file', type=str, default='find_drop.log', dest='log_file',
                        help='Specify a logging file where the log should be saved')


def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    __create_parser_arguments(parser)
    args = parser.parse_args()

    logging.basicConfig(filename=args.log_file, level=logging.DEBUG)

    rules = []
    with open(args.drop_rules_file_path) as drop_rules_file:
        docs = yaml.load_all(drop_rules_file)
        for doc in docs:
            if 'source' in doc and doc['name'].find('DRoP') >= 0:
                rules.append(util.DRoPRule.create_rule_from_yaml_dict(doc))

    with open(args.output_filename, 'w') as output_file:
        util.json_dump(rules, output_file)


if __name__ == '__main__':
    main()
