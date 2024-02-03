terraform {
  required_providers {
    heroku = {
      source  = "heroku/heroku"
      version = "~> 5.2.7"
    }
  }
}

module "cpo" {
  source  = "./modules/roamingmodule"
  app_name = "performance-cpo"
  extra_config_vars = {
    CPO = "FI*CPO"
  }
  pipeline = heroku_pipeline.roamingmodule.id
}

module "emsp" {
  source  = "./modules/roamingmodule"
  app_name = "performance-msp"
  extra_config_vars = {
    EMSP = "FI*MSP"
  }
  pipeline = heroku_pipeline.roamingmodule.id
}

resource "heroku_pipeline" "roamingmodule" {
  name = "roamingmodule"
#
#  owner {
#      id   = "594a53e1-57c7-4c67-9a0e-4b730596714a"
#      type = "user"
#  }
}





#
# The below has been moved to modules/roamingmodule
#

#resource "heroku_app" "roamingmodule" {
#  source = "./modules/roamingmodule"
#  app_name   = "performance-cpo"
#
#  config_vars = {
#    PREMIUM = 1
#    HOSTNAME = "${var.app_name}.ocpiconnector.com"
#    SCHEME = "http"
#    DJANGO_SETTINGS_MODULE = "ocpiconnector.settings"
#  }
#
#  sensitive_config_vars = {
#    SECRET_KEY = random_password.secretkey.result
#  }
#}

#resource "heroku_build" "ocpiconnector" {
#  app_id     = heroku_app.roamingmodule.id
##  buildpacks = ["https://github.com/mars/create-react-app-buildpack"]
#
#  source {
#    url     = "https://github.com/erkkiat/ocpiconnector.git"
#  }
#}

#resource "heroku_domain" "roamingconnector" {
#  app_id   = heroku_app.roamingmodule.id
#  hostname = "${var.app_name}.ocpiconnector.com"
#}

#resource "heroku_formation" "ocpiconnector" {
#  app_id     = heroku_app.roamingmodule.id
#  type       = "web"
#  quantity   = 1
#  size       = "Standard-1x"
##  depends_on = ["heroku_build.ocpiconnector"]
#}
#
#resource "heroku_addon" "redis" {
#  app_id = heroku_app.roamingmodule.id
#  plan   = "heroku-redis:mini"
#}
#
#resource "heroku_addon" "mysql" {
#  app_id = heroku_app.roamingmodule.id
#  plan   = "jawsdb:kitefin"
#}
