import os

role_options = ('CPO', 'EMSP', 'HUB', 'NSP', 'NAP', 'SCSP')


class OCPIIdentities:
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
        return item in self._identities_list

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

    def get(self, item, default=None) -> str:
        return self._identities_dict[item] if item in self._identities_dict else default


ocpi_identities = OCPIIdentities()
