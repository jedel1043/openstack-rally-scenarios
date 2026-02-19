terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
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

resource "juju_machine" "keystone" {
  count       = 3
  model_uuid  = data.juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "keystone-m${count.index}"
  constraints = "mem=4G"

  placement = try(var.placement[count.index], null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
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

  machines = toset(juju_machine.keystone[*].machine_id)

  config = {
    debug            = false
    verbose          = false
    openstack-origin = "distro"
    vip              = var.vip
  }
}

resource "juju_application" "hacluster" {
  name = "keystone-hacluster"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "hacluster"
    channel = "2.4/edge"
    base    = "ubuntu@24.04"
  }

  config = {
    cluster_count = 3
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

resource "juju_integration" "ha" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.keystone.name
    endpoint = "ha"
  }

  application {
    name     = juju_application.hacluster.name
    endpoint = "ha"
  }
}

output "app_name" {
  description = "Name of the Keystone application"
  value       = juju_application.keystone.name
}
