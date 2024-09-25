from django.contrib.admin import AdminSite


class HubAdmin(AdminSite):
    site_header = "SolidRoam Enterprise HUB Administration"
    site_title = "HUB Admin"
    index_title = "HUB dashboard"
    index_template = "admin/hub/index.html"


hub_admin_site = HubAdmin(name="hubadmin")
