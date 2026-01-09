
locals {
  services = ["keystone", "glance"]
}

resource "juju_application" "routers" {
  for_each = toset(local.services)

  name       = "${each.value}-mysql-router"
  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_integration" "mysql-to-routers" {
  for_each   = juju_application.routers
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.mysql.name
    endpoint = "db-router"
  }

  application {
    name     = each.value.name
    endpoint = "db-router"
  }
}


resource "juju_integration" "router-to-keystone" {
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.routers["keystone"].name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.keystone.name
    endpoint = "shared-db"
  }
}


resource "juju_integration" "router-to-glance" {
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.routers["glance"].name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.glance.name
    endpoint = "shared-db"
  }
}