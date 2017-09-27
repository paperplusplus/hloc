#!/usr/bin/env python3
"""Some utility functions"""
import math
import subprocess
import string
import enum
import collections
import re
import sys
import logging
import os
# import msgpack
import json
import socket
import binascii

ACCEPTED_CHARACTER = frozenset('{0}.-_'.format(string.printable[0:62]))
DROP_RULE_TYPE_REGEX = re.compile(r'<<(?P<type>[a-z]*)>>')
CLASS_IDENTIFIER = '_c'
IPV4_IDENTIFIER = 'ipv4'
IPV6_IDENTIFIER = 'ipv6'

PROBE_API_URL_PING = \
    'https://kong.speedcheckerapi.com:8443/ProbeAPIService/Probes.svc/StartPingTestByBoundingBox'
PROBE_API_URL_GET_PROBES = \
    'https://kong.speedcheckerapi.com:8443/ProbeAPIService/Probes.svc/GetProbesByBoundingBox'
EARTH_RADIUS = 6371


#######################################
#    Different utility functions      #
#######################################
def count_lines(filename):
    """"Opens the file at filename than counts and returns the number of lines"""
    count = subprocess.check_output(['wc', '-l', filename])
    line_count = int(count.decode().split(' ')[0])

    logging.info('Linecount for file: {0}'.format(line_count))
    return line_count


def seek_lines(seeking_file, seek_until_line):
    """Read number of lines definded in the seekPoint"""
    if seek_until_line <= 0:
        return
    i = 0
    for _ in seeking_file:
        i += 1
        if i == seek_until_line:
            break


def hex_for_ip(ip_address):
    """Returns the hexadecimal code for the ip address"""
    ip_blocks = ip_address.split('.')
    hexdata = ''
    # TODO use format %02x%02x%02x%02x
    for block in ip_blocks:
        hexdata += hex(int(block))[2:].zfill(2)
    return hexdata.upper()


def is_ip_hex_encoded_simple(ip_address, domain):
    """check if the ip address is encoded in hex format in the domain"""
    hex_ip = hex_for_ip(ip_address)

    return hex_ip.upper() in domain.upper()


def get_path_filename(path: str) -> str:
    """Extracts the filename from a path string"""
    if path[-1] == '/':
        raise NameError('The path leads to a directory')

    return os.path.basename(path)


def remove_file_ending(filenamepath: str) -> str:
    """Removes the fileending of the paths file"""
    return os.path.join(os.path.dirname(filenamepath),
                        '.'.join(get_path_filename(filenamepath).split('.')[:-1]))


def setup_logger(filename: str, loggername: str, loglevel: str='DEBUG') -> logging.Logger:
    """does the basic config on logging"""
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: {}'.format(loglevel))
    logging.basicConfig(filename=filename, level=numeric_level,
                        format=u'[%(asctime)s][%(name)-{}s][%(levelname)-s][%(processName)s] '
                               u'%(filename)s:%(lineno)d %(message)s'.format(len(loggername)),
                        datefmt='%d.%m %H:%M:%S')
    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    return logging.getLogger(loggername)


def parse_zmap_results(zmap_filename: str, location_name: str, present_results: dict):
    """Parses a file """
    zmap_results = {}
    if present_results:
        zmap_results = present_results.copy()
    with open(zmap_filename) as zmap_file:
        for line in zmap_file:
            if line[0:5] == 'saddr':
                continue
            zmap_result = parse_zmap_line(line)
            if zmap_result[0] in zmap_results:
                if location_name:
                    if location_name in zmap_results[zmap_result[0]]:
                        if zmap_result[1] < zmap_results[zmap_result[0]][location_name]:
                            zmap_results[zmap_result[0]][location_name] = zmap_result[1]
                    else:
                        zmap_results[zmap_result[0]][location_name] = zmap_result[1]
                else:
                    if zmap_result[1] < zmap_results[zmap_result[0]]:
                        zmap_results[zmap_result[0]] = zmap_result[1]
            else:
                if location_name:
                    zmap_results[zmap_result[0]] = {}
                    zmap_results[zmap_result[0]][location_name] = zmap_result[1]
                else:
                    zmap_results[zmap_result[0]] = zmap_result[1]

    return zmap_results


def parse_zmap_line(zmap_line):
    """Parses one line of an zmap output"""
    rsaddr, _, _, _, _, saddr, sent_ts, sent_ts_us, rec_ts, rec_ts_us, _, _, _, _, success = \
        zmap_line.split(',')
    if success:
        sec_difference = int(rec_ts) - int(sent_ts)
        u_sec_diference = (int(rec_ts_us) - int(sent_ts_us)) / 10 ** 6
        return rsaddr, (sec_difference + u_sec_diference) * 1000


def ip_to_int(ip_addr, ip_version):
    if ip_version == IPV6_IDENTIFIER:
        return int(binascii.hexlify(socket.inet_pton(socket.AF_INET6, ip_addr)), 16)
    elif ip_version == IPV4_IDENTIFIER:
        return int(binascii.hexlify(socket.inet_pton(socket.AF_INET, ip_addr)), 16)

def int_to_alphanumeric(num: int):
    rest = num % 36
    if rest < 10:
        rest_ret = '{}'.format(rest)
    else:
        rest_ret = '{}'.format(chr(ord('a')+rest-10))
    div = num // 36
    if div == 0:
        return rest_ret
    else:
        return int_to_alphanumeric(div) + rest_ret


###################################################################################################
#                                    JSON utility functions                                       #
###################################################################################################
def json_object_encoding(obj):
    """Overrides the default method from the JSONEncoder"""
    if isinstance(obj, JSONBase):
        return obj.dict_representation()

    raise TypeError('Object not handled by the JSON encoding function ({})'.format(type(obj)))


def json_object_decoding(dct):
    """Decodes the dictionary to an object if it is one"""
    if CLASS_IDENTIFIER in dct:
        if dct[CLASS_IDENTIFIER] == Location.class_name_identifier:
            return Location.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == AirportInfo.class_name_identifier:
            return AirportInfo.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == LocodeInfo.class_name_identifier:
            return LocodeInfo.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == LocationResult.class_name_identifier:
            return LocationResult.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == Domain.class_name_identifier:
            return Domain.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == DomainLabel.class_name_identifier:
            return DomainLabel.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == DomainLabelMatch.class_name_identifier:
            return DomainLabelMatch.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == GPSLocation.class_name_identifier:
            return GPSLocation.create_object_from_dict(dct)
        if dct[CLASS_IDENTIFIER] == DRoPRule.class_name_identifier:
            return DRoPRule.create_object_from_dict(dct)
    return dct


def json_dump(encoding_var, file_ptr):
    """
    Dumps the encoding_var to the file in file_ptr with the
    json_object_encoding function
    :param encoding_var: the variable you want to encode in json
    :param file_ptr: the file where the
    :return: None
    """
    # msgpack.pack(encoding_var, file_ptr, default=json_object_encoding)
    json.dump(encoding_var, file_ptr, default=json_object_encoding)


def json_load(file_ptr):
    """
    Loads the content of the file and returns the decoded result
    :param file_ptr: the pointer to the file where json should load and decode
    :return: the variable from json.load
    """
    # sreturn msgpack.unpack(file_ptr, object_hook=json_object_decoding)
    return json.load(file_ptr, object_hook=json_object_decoding)


def json_loads(json_str):
    """
    Decodes the content of the string variable and returns it
    :param json_str: the string which content should be decoded
    :return: the variable from json.loads
    """
    # return msgpack.unpackb(json_str, object_hook=json_object_decoding)
    return json.loads(json_str, object_hook=json_object_decoding)


#######################################
#       Models and Interfaces         #
#######################################
@enum.unique
class LocationCodeType(enum.Enum):
    iata = 0
    icao = 1
    faa = 2
    clli = 3
    locode = 4
    geonames = 5

    @property
    def regex(self):
        """
        :returns the pattern for regex matching a code of the type
        :return: str
        """
        base = r'[a-zA-Z]'
        if self == LocationCodeType.iata:
            pattern = base + r'{3}'
        elif self == LocationCodeType.icao:
            pattern = base + r'{4}'
        elif self == LocationCodeType.clli:
            pattern = base + r'{6}'
        elif self == LocationCodeType.locode:
            pattern = base + r'{5}'
        elif self == LocationCodeType.geonames:
            pattern = r'[a-zA-Z]+'
        else:
            logging.error('WTF? should not be possible')
            return

        return r'(?P<type>' + pattern + r')'


@enum.unique
class DomainType(enum.Enum):
    correct = '0'
    not_responding = '1'
    no_location = '2'
    no_verification = '3'
    blacklisted = '4'


class JSONBase(object):
    """
    The Base class to JSON encode your object with json_encoding_func
    """
    # TODO use ABC
    class_name_identifier = None

    def dict_representation(self):
        raise NotImplementedError("JSONBase: Should have implemented this method")

    @staticmethod
    def create_object_from_dict(dct):
        raise NotImplementedError("JSONBase: Should have implemented this method")

    def copy(self):
        raise NotImplementedError("JSONBase: Should have implemented this method")


class GPSLocation(JSONBase):
    """holds the coordinates"""

    class_name_identifier = 'gl'

    __slots__ = ['_id', 'lat', 'lon']

    class PropertyKey:
        id = '0'
        lat = '1'
        lon = '2'

    def __init__(self, lat, lon):
        """init"""
        self._id = None
        self.lat = lat
        self.lon = lon

    @property
    def id(self):
        """Getter for id"""
        return self._id

    @id.setter
    def id(self, new_id):
        """Setter for id"""
        if new_id is None:
            self._id = None
            return
        try:
            self._id = int(new_id)
        except (ValueError, TypeError):
            logging.critical('Error: GPSLocation.id must be an Integer!', file=sys.stderr)
            raise

    def is_in_radius(self, location, radius):
        """Returns a True if the location is within the radius with the haversine method"""
        return self.gps_distance_haversine(location) <= radius

    def gps_distance_equirectangular(self, location):
        """Return the distance between the two locations using the equirectangular method"""
        lon1 = math.radians(float(self.lon))
        lat1 = math.radians(float(self.lat))
        lon2 = math.radians(float(location.lon))
        lat2 = math.radians(float(location.lat))

        return math.sqrt((((lon2 - lon1) * math.cos(0.5 * (lat2 + lat1))) ** 2 + (
            lat2 - lat1) ** 2)) * EARTH_RADIUS

    def gps_distance_haversine(self, location2):
        """
        Calculate the distance (km) between two points
        on the earth (specified in decimal degrees)
        """
        # convert decimal degrees to radians
        lon1 = math.radians(float(self.lon))
        lat1 = math.radians(float(self.lat))
        lon2 = math.radians(float(location2.lon))
        lat2 = math.radians(float(location2.lat))
        # haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        tmp = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        ftmp = 2 * math.asin(math.sqrt(tmp))
        # Radius of earth in kilometers. Use 3956 for miles
        return ftmp * EARTH_RADIUS

    def location_with_distance_and_bearing(self, distance: float, bearing: float):
        """
        Calculate a new Location with the distance from this location in km and in
        direction of bearing
        :param distance: the distance in km
        :param bearing: the bearing in degrees 0 is north and it goes clockwise
        :return: a new location in direction of bearing with the distance
        """
        bearing_rad = math.radians(bearing)
        angular_dist = distance/EARTH_RADIUS
        lat_rad = math.radians(float(self.lat))
        lon_rad = math.radians(float(self.lon))

        lat_new = math.asin(math.sin(lat_rad)*math.cos(angular_dist) +
                            math.cos(lat_rad)*math.sin(angular_dist)*math.cos(bearing_rad))
        lon_new_temp = math.atan2(
            math.sin(bearing_rad)*math.sin(angular_dist)*math.cos(lat_rad),
            math.cos(angular_dist)-math.sin(lat_rad)*math.sin(lat_new))
        lon_new = ((lon_rad - lon_new_temp + math.pi) % (2*math.pi)) - math.pi

        return GPSLocation(math.degrees(lat_new), math.degrees(lon_new))


    def dict_representation(self):
        """Returns a dictionary with the information of the object"""
        ret_dict = {
            CLASS_IDENTIFIER: self.class_name_identifier,
            GPSLocation.PropertyKey.lat: self.lat,
            GPSLocation.PropertyKey.lon: self.lon
        }
        if self.id is not None:
            ret_dict[GPSLocation.PropertyKey.id] = self.id

        return ret_dict

    @staticmethod
    def create_object_from_dict(dct):
        """Creates a Location object from a dictionary"""
        obj = GPSLocation(dct[GPSLocation.PropertyKey.lat], dct[GPSLocation.PropertyKey.lon])
        if GPSLocation.PropertyKey.id in dct:
            obj.id = dct[GPSLocation.PropertyKey.id]
        return obj

    def copy(self):
        obj = GPSLocation(self.lat, self.lon)
        obj.id = self.id
        return obj


class Location(GPSLocation):
    """
    A location object with the location name, coordinates and location codes
    Additionally information like the population can be saved
    """

    class_name_identifier = 'loc'

    __slots__ = ['lat', 'lon', 'city_name', 'state', 'state_code', 'population',
                 'airport_info', 'locode', 'clli', 'alternate_names', 'nodes',
                 'available_nodes', 'has_probeapi']

    class PropertyKey:
        city_name = '3'
        state = '4'
        state_code = '5'
        population = '6'
        clli = '7'
        alternate_names = '8'
        airport_info = '9'
        locode = 'a'
        nodes = 'b'
        available_nodes = 'c'
        has_probeapi = 'd'

    def __init__(self, lat, lon, city_name=None, state=None, state_code=None,
                 population=0):
        """init"""
        self.city_name = city_name
        self.state = state
        self.state_code = state_code
        self.population = population
        self.airport_info = None
        self.locode = None
        self.clli = []
        self.alternate_names = []
        self.nodes = None
        self.available_nodes = None
        self.has_probeapi = False
        super().__init__(lat, lon)

    def add_airport_info(self):
        """Creates and sets a new empty AirportInfo object"""
        if self.airport_info is None:
            self.airport_info = AirportInfo()

    def add_locode_info(self):
        """Creates and sets a new empty """
        if self.locode is None:
            self.locode = LocodeInfo()

    def dict_representation(self):
        """Returns a dictionary with the information of the object"""
        ret_dict = super().dict_representation()
        del ret_dict[CLASS_IDENTIFIER]
        ret_dict.update({
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.city_name: self.city_name,
            self.PropertyKey.state: self.state,
            self.PropertyKey.state_code: self.state_code,
            self.PropertyKey.population: self.population,
            self.PropertyKey.clli: self.clli,
            self.PropertyKey.alternate_names: self.alternate_names,
        })
        if self.airport_info:
            ret_dict[self.PropertyKey.airport_info] = self.airport_info.dict_representation()

        if self.locode:
            ret_dict[self.PropertyKey.locode] = self.locode.dict_representation()

        if self.available_nodes:
            ret_dict[self.PropertyKey.available_nodes] = self.available_nodes

        if self.nodes:
            ret_dict[self.PropertyKey.nodes] = self.nodes

        if self.has_probeapi:
            ret_dict[self.PropertyKey.has_probeapi] = [loc.dict_representation()
                                                       for loc in self.has_probeapi]

        return ret_dict

    def code_id_type_tuples(self):
        """
        Creates a list with all codes in a tuple with the location id
        ONLY FOR TRIE CREATION
        :rtype: list(tuple)
        """
        # if not isinstance(self.id, int):
        #     print(self.dict_representation(), 'has no id')
        #     raise ValueError('id is not int')
        ret_list = []
        if self.city_name:
            ret_list.append((self.city_name.lower(), (self.id, LocationCodeType.geonames.value)))
        for code in self.clli:
            ret_list.append((code.lower(), (self.id, LocationCodeType.clli.value)))
        for name in self.alternate_names:
            if name:
                ret_list.append((name.lower(), (self.id, LocationCodeType.geonames.value)))
        if self.locode and self.state_code:
            for code in self.locode.place_codes:
                ret_list.append(('{}{}'.format(self.state_code.lower(), code.lower()),
                                 (self.id, LocationCodeType.locode.value)))
        if self.airport_info:
            for code in self.airport_info.iata_codes:
                ret_list.append((code.lower(), (self.id, LocationCodeType.iata.value)))
            for code in self.airport_info.icao_codes:
                ret_list.append((code.lower(), (self.id, LocationCodeType.icao.value)))
            for code in self.airport_info.faa_codes:
                ret_list.append((code.lower(), (self.id, LocationCodeType.faa.value)))
        return ret_list

    @staticmethod
    def create_object_from_dict(dct):
        """Creates a Location object from a dictionary"""
        obj = Location(dct[GPSLocation.PropertyKey.lat], dct[GPSLocation.PropertyKey.lon],
                       dct[Location.PropertyKey.city_name], dct[Location.PropertyKey.state],
                       dct[Location.PropertyKey.state_code], dct[Location.PropertyKey.population])

        if Location.PropertyKey.clli in dct:
            obj.clli = dct[Location.PropertyKey.clli]
        if Location.PropertyKey.alternate_names in dct:
            obj.alternate_names = dct[Location.PropertyKey.alternate_names]
        if GPSLocation.PropertyKey.id in dct:
            obj.id = dct[GPSLocation.PropertyKey.id]
        if Location.PropertyKey.airport_info in dct:
            obj.airport_info = dct[Location.PropertyKey.airport_info]
        if Location.PropertyKey.locode in dct:
            obj.locode = dct[Location.PropertyKey.locode]
        if Location.PropertyKey.available_nodes in dct:
            obj.available_nodes = dct[Location.PropertyKey.available_nodes]
        if Location.PropertyKey.nodes in dct:
            obj.nodes = dct[Location.PropertyKey.nodes]
        if Location.PropertyKey.has_probeapi in dct:
            obj.has_probeapi = dct[Location.PropertyKey.has_probeapi]
        return obj

    def copy(self):
        obj = Location(self.lat, self.lon, self.city_name, self.state, self.state_code,
                       self.population)
        obj.id = self.id
        obj.clli = clli
        obj.airport_info = self.airport_info.copy()
        obj.locode = self.locode.copy()
        obj.available_nodes = self.available_nodes.copy()
        obj.nodes = self.nodes.copy()
        return obj


class AirportInfo(JSONBase):
    """Holds a list of the different airport codes"""

    class_name_identifier = 'ai'

    __slots__ = ['iata_codes', 'icao_codes', 'faa_codes']

    class PropertyKey:
        iata_codes = '0'
        icao_codes = '1'
        faa_codes = '2'

    def __init__(self):
        """init"""
        self.iata_codes = []
        self.icao_codes = []
        self.faa_codes = []

    def dict_representation(self):
        """Returns a dictionary with the information of the object"""
        return {
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.iata_codes: self.iata_codes,
            self.PropertyKey.icao_codes: self.icao_codes,
            self.PropertyKey.faa_codes: self.faa_codes
        }

    @staticmethod
    def create_object_from_dict(dct):
        """Creates a AirportInfo object from a dictionary"""
        obj = AirportInfo()
        obj.faa_codes = dct[AirportInfo.PropertyKey.faa_codes]
        obj.iata_codes = dct[AirportInfo.PropertyKey.iata_codes]
        obj.icao_codes = dct[AirportInfo.PropertyKey.icao_codes]
        return obj

    def copy(self):
        obj = AirportInfo()
        obj.faa_codes = self.faa_codes[:]
        obj.icao_codes = self.icao_codes[:]
        obj.iata_codes = self.iata_codes[:]
        return obj


class LocodeInfo(JSONBase):
    """Holds a list of locode codes"""

    class_name_identifier = 'li'

    __slots__ = ['place_codes', 'subdivision_codes']

    class PropertyKey:
        place_codes = '0'
        subdivision_codes = '1'

    def __init__(self):
        """init"""
        self.place_codes = []
        self.subdivision_codes = []

    def dict_representation(self):
        """Returns a dictionary with the information of the object"""
        return {
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.place_codes: self.place_codes,
            self.PropertyKey.subdivision_codes: self.subdivision_codes
        }

    @staticmethod
    def create_object_from_dict(dct):
        """Creates a LocodeInfo object from a dictionary"""
        obj = LocodeInfo()
        obj.place_codes = dct[LocodeInfo.PropertyKey.place_codes]
        obj.subdivision_codes = dct[LocodeInfo.PropertyKey.subdivision_codes]
        return obj

    def copy(self):
        obj = LocodeInfo()
        obj.place_codes = self.place_codes[:]
        obj.subdivision_codes = self.subdivision_codes[:]
        return obj


class Domain(JSONBase):
    """
    Holds the information for one domain
    DO NOT SET the DOMAIN NAME after calling the constructor!
    """

    # TODO use ipaddress stdlib module

    class_name_identifier = 'd'

    __slots__ = ['domain_name', 'ip_address', 'ipv6_address', 'domain_labels', 'location_id',
                 'location']

    class PropertyKey:
        domain_name = '0'
        ip_address = '1'
        ipv6_address = '2'
        domain_labels = '3'
        location_id = '4'

    def __init__(self, domain_name, ip_address=None, ipv6_address=None):
        """init"""

        def create_labels() -> [DomainLabel]:
            labels = []
            for label in domain_name.split('.')[::-1]:
                labels.append(DomainLabel(label))
            return labels

        self.domain_name = domain_name
        self.ip_address = ip_address
        self.ipv6_address = ipv6_address
        self.domain_labels = create_labels()
        self.location_id = None
        self.location = None

    @property
    def drop_domain_keys(self):
        """returns only the second level domain and the top level domain"""
        domain_parts = self.domain_name.split('.')
        if len(domain_parts) <= 1:
            return domain_parts
        main_domain = '.'.join(domain_parts[-2:])
        domain_parts.pop()
        domain_parts[-1] = main_domain
        return domain_parts[::-1]

    @property
    def all_matches(self):
        """Returns all matches of the domain"""
        matches = []
        location_ids = set()
        for label in self.domain_labels[::-1]:
            for match in label.matches:
                if match.location_id not in location_ids:
                    location_ids.add(match.location_id)
                    matches.append(match)
        return matches

    @property
    def possible_matches(self):
        """Returns all matches which are possible (according to measurements)"""
        return [match for match in self.all_matches if match.possible]

    @property
    def matches_count(self) -> int:
        """Counts the amount of matches for this domain"""
        return len(self.all_matches)

    @property
    def matching_match(self):
        """Returns the match where we found the correct location"""
        for match in self.all_matches:
            if match.matching:
                return match
        else:
            return None

    def ip_for_version(self, version: str) -> str:
        """returns the version corresponding ip address"""
        if version == IPV4_IDENTIFIER:
            return self.ip_address
        elif version == IPV6_IDENTIFIER:
            return self.ipv6_address
        else:
            raise ValueError('{} is not a valid IP version'.format(version))

    def dict_representation(self) -> [str, object]:
        """Returns a dictionary with the information of the object"""
        ret_dict = {
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.domain_name: self.domain_name,
            self.PropertyKey.ip_address: self.ip_address,
            self.PropertyKey.ipv6_address: self.ipv6_address,
            self.PropertyKey.domain_labels: [label.dict_representation() for label in
                                             self.domain_labels],
        }
        if self.location_id is not None:
            ret_dict[self.PropertyKey.location_id] = self.location_id
        elif self.location:
            if isinstance(self.location, Location):
                ret_dict[self.PropertyKey.location_id] = self.location.id
            else:
                ret_dict[self.PropertyKey.location_id] = self.location.dict_representation()
        return ret_dict

    @staticmethod
    def create_object_from_dict(dct, locations: [str, object]=None):
        """Creates a Domain object from a dictionary"""
        obj = Domain(dct[Domain.PropertyKey.domain_name], dct[Domain.PropertyKey.ip_address],
                     dct[Domain.PropertyKey.ipv6_address])
        if Domain.PropertyKey.domain_labels in dct:
            del obj.domain_labels[:]
            obj.domain_labels = dct[Domain.PropertyKey.domain_labels][:]
        if Domain.PropertyKey.location_id in dct:
            if isinstance(dct[Domain.PropertyKey.location_id], (int, str)):
                obj.location_id = dct[Domain.PropertyKey.location_id]
                if locations and obj.location_id in locations:
                    obj.location = locations[obj.location_id]
            elif isinstance(dct[Domain.PropertyKey.location_id], GPSLocation):
                obj.location = dct[Domain.PropertyKey.location_id]

        return obj

    def copy(self):
        obj = Domain(self.domain_name, self.ip_address, self.ipv6_address)
        obj.domain_labels = [domain_label.copy() for domain_label in self.domain_labels]
        obj.location_id = self.location_id
        obj.location = self.location
        return obj


class DomainLabel(JSONBase):
    """The model for a domain name label"""

    class_name_identifier = 'dl'

    __slots__ = ['label', 'matches']

    class PropertyKey:
        label = '0'
        matches = '1'

    def __init__(self, label):
        """
        init
        :param label: the domain label
        """
        self.label = label
        self.matches = []

    def dict_representation(self):
        """Returns a dictionary with the information of the object"""
        return {
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.label: self.label,
            self.PropertyKey.matches: [match.dict_representation() for match in self.matches]
        }

    @staticmethod
    def create_object_from_dict(dct):
        """Creates a DomainLabel object from a dictionary"""
        obj = DomainLabel(dct[DomainLabel.PropertyKey.label])
        obj.matches = dct[DomainLabel.PropertyKey.matches][:]

        return obj

    def copy(self):
        obj = DomainLabel(self.label)
        obj.matches = [match.copy() for match in self.matches]
        return obj


class DomainLabelMatch(JSONBase):
    """The model for a Match between a domain name label and a location code"""

    class_name_identifier = 'dlm'

    __slots__ = ['location_id', 'code_type', 'code', 'matching',
                 'matching_distance', 'matching_rtt', 'possible']

    class PropertyKey:
        location_id = '0'
        code_type = '1'
        code = '2'
        matching = '3'
        matching_distance = '4'
        matching_rtt = '5'
        possible = '6'

    def __init__(self, location_id: int, code_type: LocationCodeType, code=None, possible=True):
        """init"""
        self.location_id = location_id
        self.code_type = code_type
        self.code = code
        self.matching = False
        self.matching_distance = None
        self.matching_rtt = None
        self.possible = possible

    def dict_representation(self):
        """Returns a dictionary with the information of the object"""
        dct = {
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.location_id: self.location_id,
            self.PropertyKey.code_type: self.code_type.value,
            self.PropertyKey.code: self.code,
            self.PropertyKey.possible: self.possible,
        }
        if self.matching:
            dct[self.PropertyKey.matching] = self.matching
        if self.matching_distance:
            dct[self.PropertyKey.matching_distance] = self.matching_distance
        if self.matching_rtt:
            dct[self.PropertyKey.matching_rtt] = self.matching_rtt
        return dct

    @staticmethod
    def create_object_from_dict(dct):
        """Creates a DomainLabel object from a dictionary"""
        obj = DomainLabelMatch(dct[DomainLabelMatch.PropertyKey.location_id],
                               LocationCodeType(dct[DomainLabelMatch.PropertyKey.code_type]))
        if DomainLabelMatch.PropertyKey.matching in dct:
            obj.matching = dct[DomainLabelMatch.PropertyKey.matching]
        if DomainLabelMatch.PropertyKey.matching_distance in dct:
            obj.matching_distance = dct[DomainLabelMatch.PropertyKey.matching_distance]
        if DomainLabelMatch.PropertyKey.matching_rtt in dct:
            obj.matching_rtt = dct[DomainLabelMatch.PropertyKey.matching_rtt]
        if DomainLabelMatch.PropertyKey.code in dct:
            obj.code = dct[DomainLabelMatch.PropertyKey.code]
        if DomainLabelMatch.PropertyKey.possible in dct:
            obj.possible = dct[DomainLabelMatch.PropertyKey.possible]
        return obj

    def copy(self):
        obj = DomainLabelMatch(self.location_id, self.code_type, self.code, self.possible)
        obj.matching = self.matching
        obj.matching_rtt = self.matching_rtt
        obj.matching_distance = self.matching_distance
        return obj


class LocationResult(JSONBase):
    """Stores the result for a location"""

    class_name_identifier = 'lr'

    __slots__ = ['location_id', 'rtt', 'location']

    class PropertyKey:
        location_id = '0'
        rtt = '1'

    def __init__(self, location_id: str, rtt: float, location=None):
        """init"""
        self.location_id = location_id
        self.location = location
        self.rtt = rtt

    def dict_representation(self):
        """Returns a dictionary with the information of the object"""
        return {
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.location_id: self.location_id,
            self.PropertyKey.rtt: self.rtt
        }

    @staticmethod
    def create_object_from_dict(dct: dict):
        """Creates a LocationResult object from a dictionary"""
        return LocationResult(dct[LocationResult.PropertyKey.location_id],
                              dct[LocationResult.PropertyKey.rtt])

    def copy(self):
        return LocationResult(self.location_id, self.rtt, location=self.location)


class DRoPRule(JSONBase):
    """Stores a DRoP rule to find locations in domain names"""

    class_name_identifier = 'dr'

    __slots__ = ['name', 'source', '_rules', '_regex_rules']

    class PropertyKey:
        name = '0'
        source = '1'
        rules = '2'

    def __init__(self, name: str, source: str):
        """init"""
        self.name = name
        self.source = source
        self._rules = []
        self._regex_rules = None

    def dict_representation(self) -> dict:
        """Returns a dictionary with the information of the object"""
        return {
            CLASS_IDENTIFIER: self.class_name_identifier,
            self.PropertyKey.name: self.name,
            self.PropertyKey.source: self.source,
            self.PropertyKey.rules: [rule.as_norm_dict() for rule in self._rules]
        }

    @property
    def rules(self) -> [str]:
        """
        :returns all rules saved in this object in a named tuple (rule: str, type: LocationCodeType)
        :return: list(collections.namedtuple('Rule', ['rule', 'type']))
        """
        return self._rules

    @property
    def regex_pattern_rules(self) -> [(re, LocationCodeType)]:
        """
        :returns all rules saved in this object as patterns for regex execution
        :return: list(String)
        """
        if self._regex_rules is None:
            ret_rules = []
            for rule in self._rules:
                ret_rules.append((re.compile(rule.rule.replace('{}', rule.type.regex)), rule.type))
            self._regex_rules = ret_rules

        return self._regex_rules

    def add_rule(self, rule: str, code_type: LocationCodeType):
        """adds a rule with the LocationCodeType set in type"""
        self._rules.append(DRoPRule.NamedTupleRule(rule, code_type))

    @staticmethod
    def create_object_from_dict(dct):
        """Creates a DroPRuler object from a dictionary"""
        obj = DRoPRule(dct[DRoPRule.PropertyKey.name], dct[DRoPRule.PropertyKey.source])
        for rule in dct[DRoPRule.PropertyKey.rules]:
            obj.add_rule(rule[DRoPRule.NamedTupleRule.PropertyKey.rule],
                         LocationCodeType(rule[DRoPRule.NamedTupleRule.PropertyKey.rule_type]))
        return obj

    def copy(self):
        obj = DRoPRule(self.name, self.source)
        obj._rules = [rule.copy() for rule in self._rules]
        return obj

    @staticmethod
    def create_rule_from_yaml_dict(dct):
        """Creates a DroPRule object from a DRoP-Yaml dictionary"""
        obj = DRoPRule(dct['name'][5:], dct['source'])
        for rule in dct['rules']:
            if rule['mapping_required'] != 1:
                logging.warning('mapping required != 1 for ' + rule)
            else:
                rule_type_match = DROP_RULE_TYPE_REGEX.search(rule['regexp'])
                if rule_type_match:
                    drop_rule_type = rule_type_match.group('type')
                    if drop_rule_type == 'pop':
                        our_rule_type = LocationCodeType.geonames
                    elif drop_rule_type in ['iata', 'icao', 'locode', 'clli']:
                        our_rule_type = getattr(LocationCodeType, drop_rule_type)
                    else:
                        logging.warning('drop rule type not in list: ' + drop_rule_type)
                        continue
                    rule_str = rule['regexp'].replace(rule_type_match.group(0), '{}')
                    obj.add_rule(rule_str, our_rule_type)

        return obj

    class NamedTupleRule(collections.namedtuple('Rule', ['rule', 'type'])):
        __slots__ = ()

        class PropertyKey:
            rule = '0'
            rule_type = '1'

        def as_norm_dict(self) -> dict:
            return {self.PropertyKey.rule: self.rule, self.PropertyKey.rule_type: self.type.value}

        def __str__(self):
            return 'Rule(regexrule: {}, type: {})'.format(self.rule, self.type.name)

        def copy(self):
            return DRoPRule.NamedTupleRule(self.rule, self.type)