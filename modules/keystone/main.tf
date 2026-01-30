terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

variable "model_uuid" {
  description = "Model UUID where all applications will be deployed"
  type        = string
  nullable    = false
}

variable "mysql" {
  description = "Name of the MySQL application"
  type        = string
  nullable    = false
}

variable "certificates" {
  description = "Name and endpoint of the SSL certificates application"
  type = object({
    name     = string
    endpoint = string
  })
  nullable = true
  default  = null

  validation {
    condition = (
      var.certificates == null || (
        length(trimspace(var.certificates.name)) > 0 &&
        length(trimspace(var.certificates.endpoint)) > 0
      )
    )
    error_message = "Name and endpoint for the certificates application must not be empty."
  }
}

data "juju_model" "openstack" {
  uuid = var.model_uuid
}

data "juju_application" "mysql" {
  name       = var.mysql
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "certificates" {
  count      = var.certificates != null ? 1 : 0
  name       = var.certificates.name
  model_uuid = data.juju_model.openstack.uuid
}

resource "juju_application" "mysql-router" {
  name = "keystone-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_application" "keystone" {
  name = "keystone"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "keystone"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=4G"

  config = {
    debug            = true
    verbose          = true
    openstack-origin = "distro"
  }
}

resource "juju_integration" "db-router" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = data.juju_application.mysql.name
    endpoint = "db-router"
  }

  application {
    name     = juju_application.mysql-router.name
    endpoint = "db-router"
  }
}

resource "juju_integration" "shared-db" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.keystone.name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.mysql-router.name
    endpoint = "shared-db"
  }
}

resource "juju_integration" "certificates" {
  count      = length(data.juju_application.certificates)
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.keystone.name
    endpoint = "certificates"
  }

  application {
    name     = data.juju_application.certificates[0].name
    endpoint = var.certificates.endpoint
  }
}

output "app_name" {
  description = "Name of the Keystone application"
  value       = juju_application.keystone.name
}
