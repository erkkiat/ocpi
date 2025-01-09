terraform {
  required_providers {
    heroku = {
      source  = "heroku/heroku"
      version = "~> 5.2.7"
    }
  }
}

resource "heroku_pipeline" "roamingmodule" {
  name = "roamingmodule"
#
#  owner {
#      id   = "594a53e1-57c7-4c67-9a0e-4b730596714a"
#      type = "user"
#  }
}

resource "random_password" "secretkey" {
  length           = 32
  special          = false
}

resource "heroku_app" "roamingmodule" {
  name   = var.app_name
  region = var.region

  config_vars = merge({
    SCHEME = "http"
    DJANGO_SETTINGS_MODULE = "ocpiconnector.settings"
  }, var.extra_config_vars)

  sensitive_config_vars = {
    SECRET_KEY = random_password.secretkey.result
  }
}


resource "heroku_addon" "redis" {
  app_id = heroku_app.roamingmodule.id
  plan   = "rediscloud:100"
#  plan   = "ah-redis-stackhero:ist-m4euc0"
}

resource "heroku_addon" "mysql" {
  app_id = heroku_app.roamingmodule.id
  plan   = "jawsdb:blacktip"
}

resource "heroku_addon" "newrelic" {
  app_id = heroku_app.roamingmodule.id
  plan   = "newrelic:wayne"
}

resource "heroku_addon" "moesif" {
  app_id = heroku_app.roamingmodule.id
  plan   = "moesif:free"
}

resource "heroku_addon" "papertrail" {
  app_id = heroku_app.roamingmodule.id
  plan   = "papertrail:choklad"
}

resource "heroku_pipeline_coupling" "roamingmodule" {
  app_id   = heroku_app.roamingmodule.id
  pipeline = var.pipeline
  stage    = "staging"
}

resource "heroku_app_config_association" "roamingmodule" {
  app_id = heroku_app.roamingmodule.id

  vars = {
    HOSTNAME = heroku_app.roamingmodule.heroku_hostname
  }
}

resource "heroku_formation" "roamingmodule_web" {
  app_id     = heroku_app.roamingmodule.id
  type       = "web"
  quantity   = 1
  size       = "Standard-1x"
#  depends_on = ["heroku_build.ocpiconnector"]
}

resource "heroku_formation" "roamingmodule_worker" {
  app_id     = heroku_app.roamingmodule.id
  type       = "worker"
  quantity   = 1
  size       = "Standard-2x"
#  depends_on = ["heroku_build.ocpiconnector"]
}
