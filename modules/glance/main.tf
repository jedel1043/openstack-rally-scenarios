terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

resource "juju_application" "glance" {
  name = "glance"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "glance"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=1G"

  config = {
    debug            = false
    verbose          = false
    openstack-origin = "distro"
  }
}

resource "juju_application" "mysql-router" {
  name = "glance-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}
