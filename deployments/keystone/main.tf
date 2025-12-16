terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

provider "juju" {}

resource "juju_model" "openstack" {
  name = "openstack"
}

resource "juju_application" "mysql" {
  name = "mysql"

  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "mysql-innodb-cluster"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=4G"

  config = {
    innodb-buffer-pool-size = "50%"
    max-connections         = 20000
    tuning-level            = "fast"
  }
}

resource "juju_application" "mysql-router" {
  name = "mysql-router"

  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_application" "keystone" {
  name = "keystone"

  model_uuid = juju_model.openstack.uuid

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

resource "juju_integration" "mysql-to-router" {
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.mysql.name
    endpoint = "db-router"
  }

  application {
    name     = juju_application.mysql-router.name
    endpoint = "db-router"
  }
}

resource "juju_integration" "router-to-keystone" {
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.keystone.name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.mysql-router.name
    endpoint = "shared-db"
  }
}