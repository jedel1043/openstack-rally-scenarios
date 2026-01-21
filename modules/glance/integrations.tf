resource "juju_integration" "ceph" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.glance.name
    endpoint = "ceph"
  }

  application {
    name     = data.juju_application.ceph.name
    endpoint = "client"
  }
}

resource "juju_integration" "identity-service" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.glance.name
    endpoint = "identity-service"
  }

  application {
    name     = data.juju_application.keystone.name
    endpoint = "identity-service"
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
    name     = juju_application.glance.name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.mysql-router.name
    endpoint = "shared-db"
  }
}
