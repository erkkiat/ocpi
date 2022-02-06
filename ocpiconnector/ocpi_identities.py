import os

role_options = ('CPO', 'EMSP', 'HUB', 'NSP', 'NAP', 'SCSP')


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class OCPIIdentities(metaclass=Singleton):
    """
    Store the identities of this OCPI Platform in list and dict form for convenient access

    >>> i = OCPIIdentities(source=dict(CPO='FI*CCC', MSP='FI*MMM'))
    >>> i['CPO']
    'FI*CCC'
    >>> i.get('MSP')
    'FI*MMM'
    >>> i.get('AAA')
    None
    >>> i.get('AAA', 'BBB')
    'BBB'
    >>> 'FI*CCC' in i
    True
    >>> 'CPO' in i
    True
    >>> 'BBB' in i
    False
    """
    _identities_list = []
    _identities_dict = dict()

    def __init__(self, source: dict = os.environ):
        self._identities_list = list(filter(None, [source.get(i) for i in role_options if source.get(i)]))
        for n in role_options:
            item = source.get(n)
            if item:
                self._identities_dict[n] = item

    def __iter__(self):
        for i in self._identities_list:
            yield i

    def __bool__(self):
        return bool(len(self._identities_list))

    def __contains__(self, item):
        return item in self._identities_list or item in self._identities_dict

    def __sizeof__(self):
        return len(self._identities_list)

    def __getitem__(self, item) -> str:
        if isinstance(item, str):
            return self._identities_dict[item]
        return self._identities_list[item]

    def __str__(self):
        return ", ".join(self._identities_list)

    def __repr__(self):
        return self.__str__()

    def items(self):
        return self._identities_dict.items()

    def get(self, item, default=None) -> str:
        return self._identities_dict[item] if item in self._identities_dict else default


ocpi_identities = OCPIIdentities()


class OCPIPlatform(metaclass=Singleton):
    is_hub = bool('HUB' in ocpi_identities)
    is_cpo = bool('CPO' in ocpi_identities)
    is_emsp = bool('EMSP' in ocpi_identities)


ocpi_platform = OCPIPlatform()

# ic(ocpi_platform.is_hub, ocpi_platform.is_cpo, ocpi_platform.is_emsp)
