from django.db.backends.mysql.base import DatabaseWrapper

original_get_connection_params = DatabaseWrapper.get_connection_params


def custom_get_connection_params(self):
    params = original_get_connection_params(self)
    print(f"Database connection parameters: {params}")
    return params


DatabaseWrapper.get_connection_params = custom_get_connection_params

# REMOVE IT AFTER INVESTIGATION
