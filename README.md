# ocpiconnector

The OCPI Connector provides a simple restful API for connecting an existing EV platforms
to roaming partners and networks. The API is proprietary and the result of three years of work with
multiple MSPs and CPOs. The API was built on the Open Charge Point Interface (OCPI) standard,
but it accommodates OCPI as well.

## Development Setup
* Clone the repository
* Create a virtualenv by following running `python3 -m venv venv`
* Activate the virtualenv by running `source venv/bin/activate`
* Install the dependencies by running `pip install -r requirements.txt`
* Install pre-commit hooks by running `pre-commit install`
* Make sure migrations are included if any model has been changed. Pre-commit hook will let you know if any migrations are missing

### Running the server locally
* Make sure you have docker installed
* Start the docker container by running `docker-compose up`
* Rename `env.example` to `.env` current one should be fine but update the values if needed, 
* Run the server by running `python manage.py runserver`
* For performance testing you can use `performancetest/gunicorn-run.sh`

## Development Guidelines
* For python let's follow the patterns https://docs.quantifiedcode.com/python-anti-patterns/index
* For the code design and practice, let's follow the [domain design pattern](https://martinfowler.com/tags/domain%20driven%20design.html) as much as applicable
* For structuring the code abd separating the business logic and db logic, Let's try to do the following
  * `models.py` - Should contain the database models
  * `services` - Should contain the business logic
  * `repositories` - Should contain the database interfaces e.g get_user_by_id, get_user_by_email etc
  * `serializers/schemas` - Should contain the serializers for the models/domainspecific in these cases, let's try to build the apis using django-ninja
  * `api` - Should contain the api endpoints, let's start using django-ninja for building any new APIs


_Note: This is a work in progress and will be updated as we go along_
```
