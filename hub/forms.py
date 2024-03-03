from django import forms

from ocpi22.models.credentials import Credentials


class CredentialsBasicForm(forms.ModelForm):
    class Meta:
        model = Credentials
        exclude = ['created']
