variable "app_name" {
  description = "The name of the Heroku app"
  type        = string
}

variable "region" {
  description = "The region to deploy the Heroku app in"
  default     = "eu"
  type        = string
}

variable "extra_config_vars" {
  description = "Additional configuration variables for the Heroku app"
  type        = map(string)
  default     = {}
}

variable "pipeline" {
  description = "Pipeline for the app to be attached to"
  type        = string
}
