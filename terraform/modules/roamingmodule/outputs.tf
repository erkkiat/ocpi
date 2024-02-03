output "app_name" {
  value = heroku_app.roamingmodule.name
}

output "app_url" {
  value = heroku_app.roamingmodule.heroku_hostname
}

#output "jawsdb_url" {
#  value = heroku_addon.mysql.config_vars["JAWSDB_URL"]
#}
