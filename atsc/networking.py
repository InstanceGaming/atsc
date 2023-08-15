from netifaces import AF_INET, ifaddresses


def get_address_v4(filter_if_name: str):
    interface = ifaddresses(filter_if_name)
    protocol = interface[AF_INET]
    return protocol[0]['addr']
