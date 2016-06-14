#!/usr/bin/env python3
"""
This module checks the location information found with different verifing methods
"""
import argparse
import ujson as json
import requests
import time
import os.path
import geoip2.database
import subprocess
import random
import mmap
import sys
import IP2Location
import logging
import multiprocessing as mp
import ripe.atlas.cousteau as ripe_atlas
from threading import Thread, Semaphore, Lock
from math import ceil


import src.data_processing.util as util

API_KEY = '1dc0b3c2-5e97-4a87-8864-0e5a19374e60'
RIPE_SESSION = requests.Session()
MAX_RTT = 9
ALLOWED_MEASUREMENT_AGE = 60 * 60 * 24 * 350  # 350 days in seconds
ATLAS_URL = 'https://atlas.ripe.net'
API_MEASUREMENT_POINT = '/api/v1/measurement'
MEASUREMENT_URL = ATLAS_URL + API_MEASUREMENT_POINT + '/'

LOCATION_RADIUS = 100
LOCATION_RADIUS_PRECOMPUTED = (LOCATION_RADIUS / 6371) ** 2
DISTANCE_METHOD = util.GPSLocation.gps_distance_equirectangular
MUNICH_ID = 'munich'
DALLAS_ID = 'dallas'
SINGAPORE_ID = 'singapore'
COORDS = {
    MUNICH_ID: {'gps_coords': util.GPSLocation(lat=48.137357, lon=11.575288)},
    DALLAS_ID: {'gps_coords': util.GPSLocation(lat=32.776664, lon=-96.796988)},
    SINGAPORE_ID: {'gps_coords': util.GPSLocation(lat=1.352083, lon=103.874949)}
}


def __create_parser_arguments(parser):
    """Creates the arguments for the parser"""
    parser.add_argument('filename_proto', type=str,
                        help=r'The path to the files with {} instead of the filenumber'
                             ' in the name so it is possible to format the string')
    parser.add_argument('-f', '--file-count', type=int, default=8,
                        dest='fileCount',
                        help='number of files from preprocessing')
    parser.add_argument('-l', '--location-file-name', required=True, type=str,
                        dest='locationFile',
                        help='The path to the location file.'
                             ' The output file from the codes_parser')
    parser.add_argument('-m', '--method', type=str, dest='verifingMethod',
                        choices=['geoip', 'ip2location', 'ripe'],
                        default='ripe',
                        help='Specify the method with wich the locations should be checked')
    # parser.add_argument('-d', '--ripe-node-distance', type=int, dest='ripeDistance',
    #                     default=250, help='This number defines the maximum distance between'
    #                     ' a ripe probe and the suspected location.')
    parser.add_argument('-g', '--geoip-database', type=str, dest='geoipFile',
                        help='If you choose the geoip method you have to'
                             ' specify the path to the database in this argument')
    parser.add_argument('-i', '--ip2location-database', type=str,
                        dest='ip2locFile',
                        help='If you choose the ip2location as method you have to'
                             ' specify the path to the database in this argument.\n'
                             'Currently not tested, because no database is available')
    parser.add_argument('-r', '--rtt-file-proto', type=str, dest='rtt_proto',
                        help='If specified the rtt times will be read from the file '
                             'prototype for every input file. It must '
                             'contain a rtt for every ip in the input files')
    parser.add_argument('-q', '--ripe-request-limit', type=int,
                        dest='ripeRequestLimit',
                        help='How many request should normally be allowed per second '
                             'to the ripe server', default=10)
    parser.add_argument('-b', '--ripe-request-burst-limit', type=int,
                        dest='ripeRequestBurstLimit',
                        help='How many request should at maximum be allowed per second'
                             ' to the ripe server', default=15)
    parser.add_argument('-l', '--logging-file', type=str, default='find_trie.log', dest='log_file',
                        help='Specify a logging file where the log should be saved')


def __check_args(args):
    """Checks arguments validity"""
    if args.filename_proto.find('{}') < 0:
        raise ValueError(
            'Wrong format for the filename! It must be formatable with the '
            '{}-brackets where the numbers have to be inserted.')

    if args.verifingMethod == 'geoip':
        if args.geoipFile is None:
            raise ValueError(
                'Please specify the file location of the geoip database!')
        if not os.path.isfile(args.geoipFile):
            raise ValueError('Path to geoip database does not exist!')

    if args.verifingMethod == 'ip2location':
        if args.ip2locFile is None:
            raise ValueError(
                'Please specify the file location of the ip2lcation database!')
        if not os.path.isfile(args.ip2locFile):
            raise ValueError('Path to ip2location database does not exist!')


def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    __create_parser_arguments(parser)
    args = parser.parse_args()
    __check_args(args)

    util.setup_logging(args.log_file)

    start_time = time.time()
    with open(args.locationFile) as locationFile:
        locations = util.json_load(locationFile)

    if args.verifingMethod == 'ripe':
        ripe_slow_down_sema = mp.BoundedSemaphore(args.ripeRequestBurstLimit)
        ripe_create_sema = mp.Semaphore(100)
        generator_thread = Thread(target=generate_ripe_request_tokens,
                                  args=(ripe_slow_down_sema, args.ripeRequestLimit))
        generator_thread.deamon = True

        if next(iter(locations.values())).nodes is None:
            for location in locations.values():
                nodes, available_nodes = get_nearest_ripe_nodes(location, 1000)
                location.nodes = nodes
                location.available_nodes = available_nodes
            with open(args.locationFile, 'w') as locationFile:
                util.json_dump(locations, locationFile)

        null_locations = []
        for location in locations.values():
            if len(location.near_nodes) == 0:
                null_locations.append(location)

        with open('locations_wo_nodes.json', 'w') as loc_wo_nodes_file:
            util.json_dump(null_locations, loc_wo_nodes_file)

        COORDS[MUNICH_ID]['distances'] = {}
        COORDS[DALLAS_ID]['distances'] = {}
        COORDS[SINGAPORE_ID]['distances'] = {}
        for location in locations.values():
            COORDS[MUNICH_ID]['distances'][str(location['id'])] = \
                DISTANCE_METHOD(location, COORDS[MUNICH_ID]['gps_coords'])
            COORDS[DALLAS_ID]['distances'][str(location['id'])] = \
                DISTANCE_METHOD(location, COORDS[DALLAS_ID]['gps_coords'])
            COORDS[SINGAPORE_ID]['distances'][str(location['id'])] = \
                DISTANCE_METHOD(location, COORDS[SINGAPORE_ID]['gps_coords'])

    logging.info('finished ripe after {}'.format((time.time() - start_time)))

    processes = []
    for pid in range(0, args.fileCount):
        process = None
        if args.verifingMethod == 'ripe':
            process = mp.Process(target=ripe_check_for_list,
                                 args=(args.filename_proto,
                                       pid,
                                       locations,
                                       args.rtt_proto,
                                       ripe_create_sema,
                                       ripe_slow_down_sema))
        elif args.verifingMethod == 'geoip':
            process = mp.Process(target=geoip_check_for_list,
                                 args=(args.filename_proto,
                                       pid,
                                       locations,
                                       args.geoipFile))
        elif args.verifingMethod == 'ip2location':
            process = mp.Process(target=ip2location_check_for_list,
                                 args=(args.filename_proto,
                                       pid,
                                       locations,
                                       args.ip2locFile))
        processes.append(process)

    for process in processes:
        process.start()

    if args.verifingMethod == 'ripe':
        generator_thread.start()

    alive = 8
    while alive > 0:
        try:
            for process in processes:
                process.join()
            process_sts = [pro.is_alive() for pro in processes]
            if process_sts.count(True) != alive:
                logging.info(process_sts.count(True), 'processes alive')
                alive = process_sts.count(True)
        except KeyboardInterrupt:
            pass

    end_time = time.time()
    logging.info('running time: {}'.format((end_time - start_time)))
    sys.exit(0)


def generate_ripe_request_tokens(sema, limit):
    """
    Generates RIPE_REQUESTS_PER_SECOND tokens on the Semaphore
    """
    while True:
        time.sleep(2 / limit)
        try:
            sema.release()
            sema.release()
        except ValueError:
            continue


def ip2location_check_for_list(filename_proto, pid, locations,
                               ip2locations_filename):
    """Verifies the locations with the ip2locations database"""
    ip2loc_obj = IP2Location.IP2Location()
    ip2loc_obj.open(ip2locations_filename)

    location_domain_file = open(filename_proto.format(pid) + '.locations', 'w')

    correct_count = {
        'iata': 0, 'icao': 0, 'faa': 0, 'clli': 0, 'alt': 0, 'locode': 0
        }

    with open(filename_proto.format(pid)) as domainFile:
        domain_file_mm = mmap.mmap(domainFile.fileno(), 0, access=mmap.ACCESS_READ)
        line = domain_file_mm.readline().decode('utf-8')
        while len(line) > 0:
            domain_location_list = util.json_loads(line)
            correct_locs = []
            wrong_locs = []
            for domain in domain_location_list:
                location_label_match = ip2loc_get_domain_location(domain,
                                                                  ip2loc_obj,
                                                                  locations,
                                                                  correct_count)
                if location_label_match is not None:
                    domain.location_match = location_label_match
                    correct_locs.append(domain)
                else:
                    wrong_locs.append(domain)
            util.json_dump(correct_locs, location_domain_file)
            location_domain_file.write('\n')
            line = domain_file_mm.readline().decode('utf-8')


def ip2loc_get_domain_location(domain, ip2loc_reader, locations, correct_count):
    """checks the domains locations with the geoipreader"""
    ip_location = ip2loc_reader.get_all(domain.ip_address)
    for i, label in enumerate(domain.domain_labels):
        if i == 0:
            # skip if tld
            continue

        for match in label.matches:
            if ip_location.country_short == locations[str(match.location_id)].stateCode:
                correct_count[match.code_type] += 1
                return match

    return None


def geoip_check_for_list(filename_proto, pid, locations, geoip_filename):
    """Verifies the location with the geoip database"""
    geoipreader = geoip2.database.Reader(geoip_filename)
    location_domain_file = open(filename_proto.format(pid) + '.locations', 'w')

    correct_count = {
        'iata': 0, 'icao': 0, 'faa': 0, 'clli': 0, 'alt': 0, 'locode': 0
        }

    with open(filename_proto.format(pid)) as domainFile:
        domain_file_mm = mmap.mmap(domainFile.fileno(), 0, access=mmap.ACCESS_READ)
        line = domain_file_mm.readline().decode('utf-8')
        while len(line) > 0:
            domain_location_list = util.json_loads(line)
            correct_locs = []
            wrong_locs = []
            for domain in domain_location_list:
                matching_location = geoip_get_domain_location(domain,
                                                              geoipreader,
                                                              locations,
                                                              correct_count)
                if matching_location is not None:
                    domain.location_match = matching_location
                    correct_locs.append(domain)
                else:
                    wrong_locs.append(domain)
            util.json_dump(correct_locs, location_domain_file)
            location_domain_file.write('\n')
            line = domain_file_mm.readline().decode('utf-8')

    location_domain_file.close()
    geoipreader.close()
    logging.info('correct count: {}'.format(correct_count))


def geoip_get_domain_location(domain, geoipreader, locations, correct_count):
    """checks the domains locations with the geoipreader"""
    geoip_location = geoipreader.city(domain.ip)
    if (
                geoip_location.location is None or geoip_location.location.longitude is None or
            geoip_location.location.latitude is None):
        return None
    for i, label in enumerate(domain.domainLabels):
        if i == 0:
            # skip if tld
            continue

        for match in label.matches:
            if locations[match.location_id].is_in_radius(
                    util.GPSLocation(geoip_location.location.latitude,
                                     geoip_location.location.longitude)):
                correct_count[match['type']] += 1
                return match

    return None


def ripe_check_for_list(filename_proto, pid, locations, rtt_proto,
                        ripe_create_sema, ripe_slow_down_sema):
    """Checks for all domains if the suspected locations are correct"""
    thread_count = 25
    thread_semaphore = Semaphore(thread_count)

    count_lock = Lock()
    correct_count = {
        'iata': 0, 'icao': 0, 'faa': 0, 'clli': 0, 'alt': 0, 'locode': 0
        }

    chair_server_locks = {'m': Lock(), 's': Lock(), 'd': Lock()}
    rtts = None
    if rtt_proto is not None:
        with open(rtt_proto.format(pid)) as rtt_file:
            rtts = json.load(rtt_file)

    domain_lock = Lock()
    domains = {
        CORRECT_TYPE: [], NOT_RESPONDING_TYPE: [], NO_LOCATION_TYPE: [],
        BLACKLISTED_TYPE: []
        }

    domain_output_file = open('check_domains_output_{}.json'.format(pid), 'w',
                              buffering=1)

    def update_count_for_type(ctype):
        """acquires lock and increments in count the type property"""
        with count_lock:
            correct_count[ctype] += 1

    def dump_domain_list():
        """Write all domains in the buffer to the file and empty the lists"""
        logging.info('correct {} not_responding {} no_location {} blacklisted {}'.format(
            len(domains[CORRECT_TYPE]), len(domains[NOT_RESPONDING_TYPE]),
            len(domains[NO_LOCATION_TYPE]), len(domains[BLACKLISTED_TYPE])))
        util.json_dump(domains, domain_output_file)
        domain_output_file.write('\n')
        del domains[CORRECT_TYPE]
        del domains[NOT_RESPONDING_TYPE]
        del domains[NO_LOCATION_TYPE]
        del domains[BLACKLISTED_TYPE]
        domains[CORRECT_TYPE] = []
        domains[NOT_RESPONDING_TYPE] = []
        domains[NO_LOCATION_TYPE] = []
        domains[BLACKLISTED_TYPE] = []

    def update_domains(update_domain, dtype):
        """Append current domain in the domain dict to the dtype"""
        domain_lock.acquire()
        domains[dtype].append(update_domain)

        if (len(domains[CORRECT_TYPE]) + len(domains[NOT_RESPONDING_TYPE]) +
                len(domains[NO_LOCATION_TYPE]) + len(domains[BLACKLISTED_TYPE])) >= 10 ** 3:
            dump_domain_list()

        domain_lock.release()

    threads = []
    try:
        with open(filename_proto.format(pid)) as domainFile:
            domain_file_mm = mmap.mmap(domainFile.fileno(), 0, acccess=mmap.ACCESS_READ)
            line = domain_file_mm.readline().decode('utf-8')
            count_entries = 0
            while len(line) > 0:
                domain_location_list = util.json_loads(line)
                if len(threads) > thread_count:
                    remove_indexes = []
                    for t_index in range(0, len(threads)):
                        if not threads[t_index].is_alive():
                            threads[t_index].join()
                            remove_indexes.append(t_index)
                    for r_index in remove_indexes[::-1]:
                        threads.remove(threads[r_index])
                for domain in domain_location_list:
                    thread_semaphore.acquire()
                    thread = Thread(target=check_domain_location_ripe,
                                    args=(pid, domain, update_domains,
                                          update_count_for_type,
                                          thread_semaphore,
                                          locations, chair_server_locks, rtts,
                                          ripe_create_sema,
                                          ripe_slow_down_sema))
                    thread.start()
                    threads.append(thread)
                    count_entries += 1
                    if count_entries % 10000 == 0:
                        logging.info('count {} correct_count {}'.format(count_entries,
                                                                        correct_count))
                line = domain_file_mm.readline().decode('utf-8')

            domain_file_mm.close()
    except KeyboardInterrupt:
        pass

    for thread in threads:
        thread.join()

    util.json_dump(domains, domain_output_file)
    logging.info('correct_count {}'.format(correct_count))


CORRECT_TYPE = 'correct'
NOT_RESPONDING_TYPE = 'not_responding'
NO_LOCATION_TYPE = 'no_location'
BLACKLISTED_TYPE = 'blacklisted'


def check_domain_location_ripe(pid, domain, update_domains,
                               update_count_for_type,
                               sema, locations, chair_server_locks,
                               rtts, ripe_create_sema, ripe_slow_down_sema):
    """checks if ip is at location"""
    try:
        matched = False

        results = None
        if rtts is not None and domain['ip'] in rtts.keys():
            if rtts[domain['ip']]['blacklisted']:
                update_domains(domain, BLACKLISTED_TYPE)
                return

            results = [util.LocationResult(MUNICH_ID,
                                           rtts[domain['ip']]['rtt'][MUNICH_ID],
                                           COORDS[MUNICH_ID]['gps_coords']),
                       util.LocationResult(SINGAPORE_ID,
                                           rtts[domain['ip']]['rtt'][SINGAPORE_ID],
                                           COORDS[SINGAPORE_ID]['gps_coords']),
                       util.LocationResult(DALLAS_ID,
                                           rtts[domain['ip']]['rtt'][DALLAS_ID],
                                           COORDS[DALLAS_ID]['gps_coords'])]
        else:
            results = test_netsec_server(domain['ip'], chair_server_locks)
        if results is None or len(
                [res for res in results if res.rtt is not None]) == 0:
            update_domains(domain, NOT_RESPONDING_TYPE)
            return

        # TODO refactoring measurements are in dict format
        measurements = [mes for mes in
                        get_measurements(domain.ip, ripe_slow_down_sema)]
        logging.info('ip {} got measurements {}'.format(domain['ip'], len(measurements)))

        # TODO change algorithm to choose next match sort by longest match
        for i, label in enumerate(domain.domain_labels):
            # skip if tld
            if i == 0:
                continue

            matches = label.matches[:]

            def get_next_match():
                """

                :rtype: DomainLabelMatch
                """
                nonlocal matches
                matches = sort_matches(matches, results, locations)
                ret = None
                if len(matches) > 0:
                    ret = matches[0]
                return ret

            next_match = get_next_match()
            while next_match is not None:
                location = locations[next_match.location_id]
                near_nodes = location.nodes

                if len(near_nodes) == 0:
                    matches.remove(next_match)
                    next_match = get_next_match()
                    continue

                chk_m, node = check_measurements_for_nodes(measurements,
                                                           location,
                                                           results,
                                                           ripe_slow_down_sema)

                if node is not None:
                    node_location_dist = location.gps_distance_equirectangular(
                        util.GPSLocation(node['latitude'], node['longitude']))
                if chk_m is None or chk_m == -1:
                    # only if no old measurement exists
                    m_results, near_node = create_and_check_measurement(
                        domain.ip,
                        location,
                        ripe_create_sema,
                        ripe_slow_down_sema)
                    if near_node is not None:
                        node_location_dist = location.gps_distance_equirectangular(
                            util.GPSLocation(near_node['latitude'], near_node['longitude']))

                    if m_results is None:
                        matches.remove(next_match)
                        next_match = get_next_match()
                        continue

                    result = next(iter(m_results))

                    if result is None:
                        matches.remove(next_match)
                        next_match = get_next_match()
                        continue

                    chk_res = get_rtt_from_result(result)

                    if chk_res is None:
                        matches.remove(next_match)
                        next_match = get_next_match()
                        continue
                    elif chk_res == -1:
                        update_domains(domain, NOT_RESPONDING_TYPE)
                        return
                    elif chk_res < (MAX_RTT + node_location_dist / 100):
                        update_count_for_type(next_match.code_type)
                        matched = True
                        next_match.matching = near_node
                        domain.location = location
                        update_domains(domain, CORRECT_TYPE)
                        break
                    else:
                        n_res = util.LocationResult(location.id, chk_res, location)
                        results.append(n_res)
                elif chk_m < (MAX_RTT + node_location_dist / 100):
                    update_count_for_type(next_match.code_type)
                    matched = True
                    next_match.matching = node
                    domain.location = location
                    update_domains(domain, CORRECT_TYPE)
                    break
                else:
                    n_res = util.LocationResult(location.id, chk_m, location)
                    results.append(n_res)

                matches.remove(next_match)
                next_match = get_next_match()

            if matched:
                break

        if not matched:
            update_domains(domain, NO_LOCATION_TYPE)
    finally:
        sema.release()


def sort_matches(matches, results, locations):
    """Sort the matches after their most probable location"""
    results = [result for result in results if result.rtt is not None]
    results.sort(key=lambda res: res.rtt)
    if len(results) == 0:
        return matches

    near_matches = {}
    for match in matches:
        distances = []
        for result in results:
            if result.location_id in COORDS.keys():
                distance = COORDS[result.location_id]['distances'][
                    match.location_id]
                if distance > (result.rtt * 100):
                    break
                distances.append((result, distance))
            else:
                distance = \
                    locations[result.location_id].gps_distance_equirectangular(
                        locations[match.location_id])
                if distance > (result.rtt * 100):
                    break
                distances.append((result, distance))
        if len(distances) != len(results):
            continue

        min_res = min(distances, key=lambda res: res[1])[0]

        if min_res.location_id not in near_matches.keys():
            near_matches[min_res.location_id] = []

        near_matches[min_res.location_id].append(match)

    ret = []
    for result in results:
        if result.location_id in near_matches.keys():
            ret.extend(near_matches[result.location_id])
    return ret


def test_netsec_server(ip_address, chair_server_locks):
    """Test from the network chairs server the rtts and returns them in a dict"""
    ret = []
    server_configs = {
        'm': {
            'user': 'root', 'port': 15901, 'server': 'planetlab7.net.in.tum.de'
            },
        's': {'user': 'root', 'port': None, 'server': '139.162.29.117'},
        'd': {'user': 'root', 'port': None, 'server': '45.33.5.55'}
        }
    chair_server_locks['m'].acquire()
    ret.append(util.LocationResult(MUNICH_ID,
                                   get_min_rtt(
                                       ssh_ping(server_configs['m'], ip_address)),
                                   COORDS[MUNICH_ID]['gps_coords']))
    chair_server_locks['m'].release()
    chair_server_locks['s'].acquire()
    ret.append(util.LocationResult(SINGAPORE_ID,
                                   get_min_rtt(
                                       ssh_ping(server_configs['s'], ip_address)),
                                   COORDS[SINGAPORE_ID]['gps_coords']))
    chair_server_locks['s'].release()
    chair_server_locks['d'].acquire()
    ret.append(util.LocationResult(DALLAS_ID,
                                   get_min_rtt(
                                       ssh_ping(server_configs['d'], ip_address)),
                                   COORDS[DALLAS_ID]['gps_coords']))
    chair_server_locks['d'].release()
    if ret[0].rtt is None and ret[1].rtt is None and ret[2].rtt is None:
        return None
    return ret


def ssh_ping(server_conf, ip_address):
    """Perform a ping from the server with server_conf over ssh"""
    # build ssh arguments
    args = ['ssh']
    if server_conf['port'] is not None:
        args.append('-p')
        args.append(str(server_conf['port']))
    args.append('{0}@{1}'.format(server_conf['user'], server_conf['server']))
    args.extend(['ping', '-fnc', '4', ip_address])  # '-W 1',
    try:
        output = subprocess.check_output(args, timeout=45)
    except subprocess.CalledProcessError as error:
        if error.returncode == 1:
            return None
        elif error.returncode == 255:
            time.sleep(3)
            return ssh_ping(server_conf, ip_address)
        logging.error(error.output)
        raise error
    except subprocess.TimeoutExpired:
        return None
    except:
        raise
    return str(output)


def get_min_rtt(ping_output):
    """
    parses the min rtt from a ping output
    if the host did not respond returns None
    """
    if ping_output is None:
        return None
    min_rtt_str = ping_output[(ping_output.find('mdev = ') + len('mdev = ')):]
    min_rtt_str = min_rtt_str[:min_rtt_str.find('/')]
    return float(min_rtt_str)


def get_rtt_from_result(measurement_entry):
    """gets the rtt from measurement_entry"""
    if 'min' in measurement_entry.keys():
        return measurement_entry['min']
    if 'result' in measurement_entry.keys() and len(
            measurement_entry['rtt']) > 0:
        min_rtt = min(measurement_entry['rtt'], key=lambda res: res['rtt'])[
            'rtt']
        return min_rtt
    if 'avg' in measurement_entry.keys():
        return measurement_entry['avg']
    return None


NON_WORKING_PROBES = []
NON_WORKING_PROBES_LOCK = Lock()


def create_and_check_measurement(ip_addr, location, ripe_create_sema,
                                 ripe_slow_down_sema):
    """creates a measurement for the parameters and checks for the created measurement"""
    near_nodes = [node for node in location.available_nodes if
                  node not in NON_WORKING_PROBES]

    def new_near_node():
        """Get a node from the near_nodes and return it"""
        if len(near_nodes) > 0:
            return near_nodes[random.randint(0, len(near_nodes) - 1)]
        else:
            return None

    near_node = new_near_node()
    if near_node is None:
        return None, None

    def new_measurement():
        """Create new measurement"""
        return create_ripe_measurement(ip_addr, location, near_node,
                                       ripe_slow_down_sema)

    def sleep_ten():
        """Sleep for ten seconds"""
        time.sleep(10)

    ripe_create_sema.acquire()
    try:
        measurement_id = new_measurement()
        if measurement_id is None:
            return None, None

        while True:
            if measurement_id is None:
                return None, None
            res = get_ripe_measurement(measurement_id)
            if res is not None:
                if res.status_id == 4:
                    break
                elif res.status_id in [6, 7]:
                    NON_WORKING_PROBES_LOCK.acquire()
                    NON_WORKING_PROBES.append(near_node)
                    NON_WORKING_PROBES_LOCK.release()
                    near_nodes.remove(near_node)
                    near_node = new_near_node()
                    if near_node is None:
                        return None, None
                    measurement_id = new_measurement()
                    continue
                elif res.status_id in [0, 1, 2]:
                    sleep_ten()
            else:
                sleep_ten()
        ripe_slow_down_sema.acquire()
        success, m_results = ripe_atlas.AtlasResultsRequest(
            **{'msm_id': measurement_id}).create()
        while not success:
            logging.warning('ResultRequest error {}'.format(m_results))
            time.sleep(10 + (random.randrange(0, 500) / 100))
            ripe_slow_down_sema.acquire()
            success, m_results = ripe_atlas.AtlasResultsRequest(
                **{'msm_id': measurement_id}).create()

        return m_results, near_node

    finally:
        ripe_create_sema.release()


USE_WRAPPER = True


def create_ripe_measurement(ip_addr, location, near_node, ripe_slow_down_sema):
    """Creates a new ripe measurement to the first near node and returns the measurement id"""

    def create_ripe_measurement_wrapper():
        """Creates a new ripe measurement to the first near node and returns the measurement id"""

        ping = ripe_atlas.Ping(af=4, packets=1, target=ip_addr,
                               description=ip_addr + ' test for location ' + location.city_name)
        source = ripe_atlas.AtlasSource(value=str(near_node['id']), requested=1,
                                        type='probes')
        atlas_request = ripe_atlas.AtlasCreateRequest(
            key=API_KEY,
            measurements=[ping],
            sources=[source],
            is_oneoff=True
        )
        # ripe_slow_down_sema.acquire()
        (success, response) = atlas_request.create()

        retries = 0
        while not success:
            success, response = atlas_request.create()

            if success:
                break
            time.sleep(10 + (random.randrange(0, 500) / 100))

            retries += 1
            if retries % 5 == 0:
                logging.error('Create error {}'.format(response))

        measurement_ids = response['measurements']
        return measurement_ids[0]

    def create_ripe_measurement_post():
        """Creates a new ripe measurement to the first near node and returns the measurement id"""
        headers = {
            'Content-Type': 'application/json', 'Accept': 'application/json'
            }
        payload = {
            'definitions': [
                {
                    'target': ip_addr,
                    'af': 4,
                    'packets': 1,
                    'size': 48,
                    'description': ip_addr + ' test for location ' + location[
                        'cityName'],
                    'type': 'ping',
                    'resolve_on_probe': False
                }
            ],
            'probes': [
                {
                    'value': str(near_node['id']),
                    'type': 'probes',
                    'requested': 1
                }
            ],
            'is_oneoff': True
        }

        params = {'key': API_KEY}
        ripe_slow_down_sema.acquire()
        response = requests.post('https://atlas.ripe.net/api/v1/measurement/',
                                 params=params,
                                 headers=headers, json=payload)

        retries = 0
        while response.status_code != 202 and retries < 5:
            if response.status_code == 400:
                logging.error('Create measurement error! {}'.format(response.text))
                return None
            ripe_slow_down_sema.acquire()
            response = requests.post(
                'https://atlas.ripe.net/api/v1/measurement/', params=params,
                headers=headers, json=payload)
            if response.status_code != 202:
                retries += 1

        if response.status_code != 202:
            response.raise_for_status()

        measurement_ids = response.json()['measurements']
        return measurement_ids[0]

    if USE_WRAPPER:
        return create_ripe_measurement_wrapper()
    else:
        return create_ripe_measurement_post()


def get_measurements(ip_addr, ripe_slow_down_sema):
    """
    Get ripe measurements for ip_addr
    """

    def next_batch(measurement):
        loc_retries = 0
        while True:
            try:
                measurement.next_batch()
            except ripe_atlas.exceptions.APIResponseError:
                pass
            else:
                break

            time.sleep(5)
            loc_retries += 1

            if loc_retries % 5 == 0:
                logging.warning('Ripe next_batch error! {}'.format(ip_addr))

    max_age = int(time.time()) - ALLOWED_MEASUREMENT_AGE
    params = {
        'status': '2,4,5',
        'target_ip': ip_addr,
        'type': 'ping',
        'stop_time__gte': max_age
        }
    ripe_slow_down_sema.acquire()
    retries = 0
    while True:
        try:
            measurements = ripe_atlas.MeasurementRequest(**params)
        except ripe_atlas.exceptions.APIResponseError:
            pass
        else:
            break

        time.sleep(5)
        retries += 1

        if retries % 5 == 0:
            logging.warning('Ripe MeasurementRequest error! {}'.format(ip_addr))
            time.sleep(30)
    next_batch(measurements)
    if measurements.total_count > 200:
        skip = ceil(measurements.total_count / 100) - 2

        for _ in range(0, skip):
            next_batch(measurements)

    return measurements


def get_measurements_for_nodes(measurements, ripe_slow_down_sema, near_nodes):
    """Loads all results for all measurements if they are less than a year ago"""

    for measure in measurements:
        allowed_start_time = int(time.time()) - ALLOWED_MEASUREMENT_AGE

        params = {
            'msm_id': measure['id'], 'start': allowed_start_time,
            'probe_ids': [node['id'] for node in near_nodes]
            }
        ripe_slow_down_sema.acquire()
        success, result_list = ripe_atlas.AtlasResultsRequest(**params).create()
        retries = 0
        while not success and retries < 5:
            time.sleep(10 + (random.randrange(0, 500) / 100))
            ripe_slow_down_sema.acquire()
            success, result_list = ripe_atlas.AtlasResultsRequest(**params).create()
            if not success:
                retries += 1

        if retries > 4:
            logging.error('AtlasResultsRequest error! {}'.format(result_list))
            continue

        # measure['results'] = result_list
        yield {'msm_id': measure['id'], 'results': result_list}


def check_measurements_for_nodes(measurements, location, results,
                                 ripe_slow_down_sema):
    """
    Check the measurements list for measurements from near_nodes
    :rtype: (float, dict)
    """
    if measurements is None or len(measurements) == 0:
        return None, None

    measurement_results = get_measurements_for_nodes(measurements,
                                                     ripe_slow_down_sema,
                                                     location.nodes)

    check_n = None
    node_n = None
    near_node_ids = [node['id'] for node in location.nodes]
    for m_results in measurement_results:
        for result in m_results['results']:
            oldest_alowed_time = int(time.time()) - ALLOWED_MEASUREMENT_AGE
            if (result['prb_id'] not in near_node_ids or
                    result['timestamp'] < oldest_alowed_time):
                continue
            check_res = get_rtt_from_result(result)
            if check_res is None:
                continue
            if check_res == -1 and check_n is None:
                check_n = check_res
            elif check_n is None or check_res < check_n or check_n == -1:
                node_n = next((near_node for near_node in location.nodes
                               if near_node['id'] == result['prb_id']))
                check_n = check_res
                results.append(
                    util.LocationResult(location.id, check_res, location=location))

    if check_n is not None:
        return check_n, node_n

    return None, None


def get_ripe_measurement(measurement_id):
    """Call the RIPE measurement entry point to get the ripe measurement with measurement_id"""
    retries = 0
    while True:
        try:
            return ripe_atlas.Measurement(id=measurement_id)
        except ripe_atlas.exceptions.APIResponseError:
            pass

        time.sleep(5)
        retries += 1

        if retries % 5 == 0:
            logging.warning('Ripe get Measurement error! {}'.format(measurement_id))


def json_request_get_wrapper(url, ripe_slow_down_sema, params=None,
                             headers=None):
    """Performs a GET request and returns the response dict assuming the answer is json encoded"""
    response = None
    for _ in range(0, 3):
        try:
            if ripe_slow_down_sema is not None:
                ripe_slow_down_sema.acquire()
            response = RIPE_SESSION.get(url, params=params, headers=headers,
                                        timeout=(3.05, 27.05))
            break
        except requests.exceptions.ReadTimeout:
            continue

    if response is None or response.status_code >= 500:
        return None
    if response.status_code // 100 != 2:
        response.raise_for_status()

    return response.json()


def get_nearest_ripe_nodes(location, max_distance):
    """
    Searches for ripe nodes near the location
    :rtype: (list, list)
    """
    if max_distance % 50 != 0:
        logging.critical('max_distance must be a multiple of 50')
        return None, None

    distances = [25, 50, 100, 250, 500, 1000]
    if max_distance not in distances:
        distances.append(max_distance)
        distances.sort()

    for distance in distances:
        if distance > max_distance:
            break
        params = {
            'centre': '{0},{1}'.format(location.lat, location.lon),
            'distance': str(distance)
            }

        # TODO use wrapper class
        nodes = ripe_atlas.ProbeRequest(**params)

        if nodes.total_count > 0:
            results = [node for node in nodes]
            available_probes = [node for node in results
                                if (node.status_name == 'Connected' and
                                    'system-ipv4-works' in node.tags and
                                    'system-ipv4-capable' in node.tags)]
            if len(available_probes) > 0:
                return results, available_probes
    return [], []


if __name__ == '__main__':
    main()
