from certification.decorators import register_certification_step
from ocpi22.choices import OcpiModuleEnum
from ocpiconnector import settings


class CertificationSteps:
    class LocationCertificationSteps:
        provide_paging = register_certification_step(OcpiModuleEnum.LOCATIONS, 'Demonstrate paging',
                                                     customer_initiates=False,
                                                     subtopic='Provide a paged result when requested')
        provide_filtering = register_certification_step(OcpiModuleEnum.LOCATIONS, 'Demonstrate filtering',
                                                        customer_initiates=False,
                                                        subtopic='Provide a date filtered result when requested')

    class CdrCertificationSteps:
        provide_paging = register_certification_step(OcpiModuleEnum.CDRS, 'Demonstrate paging',
                                                     customer_initiates=False)
        provide_filtering = register_certification_step(OcpiModuleEnum.CDRS, 'Demonstrate filtering',
                                                        customer_initiates=False,
                                                        subtopic='Provide a date filtered result when requested')

    class SessionCertificationSteps:
        provide_paging = register_certification_step(OcpiModuleEnum.SESSIONS, 'Demonstrate paging',
                                                     customer_initiates=False,
                                                     subtopic='Provide a paged result when requested')
        provide_filtering = register_certification_step(OcpiModuleEnum.SESSIONS, 'Demonstrate filtering',
                                                        customer_initiates=False,
                                                        subtopic='Provide a date filtered result when requested')

    class TokenCertificationSteps:
        register_certification_step(OcpiModuleEnum.TOKENS, 'Demonstrate paging', customer_initiates=False,
                                    subtopic='Provide a paged result when requested')
        register_certification_step(OcpiModuleEnum.TOKENS, 'Demonstrate filtering', customer_initiates=False,
                                    subtopic='Provide a date filtered result when requested')

    class TariffCertificationSteps:
        register_certification_step(OcpiModuleEnum.TARIFFS, 'Demonstrate paging', customer_initiates=False,
                                    subtopic='Provide a paged result when requested')
        register_certification_step(OcpiModuleEnum.TARIFFS, 'Demonstrate filtering', customer_initiates=False,
                                    subtopic='Provide a date filtered result when requested')

    class CommandCertificationSteps:
        class Receive:
            start_session = register_certification_step(OcpiModuleEnum.COMMANDS,
                                                        'Receive a START_SESSION command from the MSP',
                                                        subtopic='', customer_initiates=False)
            stop_session = register_certification_step(OcpiModuleEnum.COMMANDS,
                                                       'Receive a STOP_SESSION command from the MSP',
                                                       subtopic='', customer_initiates=False)
            reserve_now = register_certification_step(OcpiModuleEnum.COMMANDS,
                                                      'Receive a RESERVE_NOW command from the MSP',
                                                      subtopic='', customer_initiates=False)
            unlock_connector = register_certification_step(OcpiModuleEnum.COMMANDS,
                                                           'Receive a UNLOCK_CONNECTOR command from the MSP',
                                                           subtopic='', customer_initiates=False)

    class CredentialsCertificationSteps:
        sender = register_certification_step(OcpiModuleEnum.CREDENTIALS, 'Establish new Credentials as a sender')
        receiver = register_certification_step(OcpiModuleEnum.CREDENTIALS, 'Establish new Credentials as a receiver',
                                               customer_initiates=False)

    paged_list = register_certification_step(
        'PAGING', 'GET a paged list',
        subtopic='GET each page of a paged list, either Location, Session, CDR, Token or Tariff'
    )
    filtering = register_certification_step(
        'FILTERING', 'GET a filtered list', customer_initiates=False,
        subtopic='GET a filtered list for Location, Session, CDR, Token or Tariff'
    )

    headers = register_certification_step(
        'HEADERS', 'OCPI Headers',
        subtopic='OCPI-From and OCPI-To headers are required to be included in all requests'
    )


class AlwaysTrue:
    """The certification steps will be passthru if certification mode is not enabled"""
    def __getattr__(self, name):
        return True


certification_steps = CertificationSteps() if settings.CERTIFICATION_MODE else AlwaysTrue()
