resource "juju_integration" "storage-backend" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.cinder.name
    endpoint = "storage-backend"
  }

  application {
    name     = juju_application.cinder-ceph.name
    endpoint = "storage-backend"
  }
}

resource "juju_integration" "ceph" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.cinder-ceph.name
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
    name     = juju_application.cinder.name
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
    name     = juju_application.cinder.name
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
    name     = juju_application.cinder.name
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
    name     = juju_application.cinder.name
    endpoint = "ha"
  }

  application {
    name     = juju_application.hacluster.name
    endpoint = "ha"
  }
}

resource "juju_integration" "amqp" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.cinder.name
    endpoint = "amqp"
  }

  application {
    name     = data.juju_application.rabbitmq.name
    endpoint = "amqp"
  }
}

resource "juju_integration" "image-service" {
  count      = length(data.juju_application.glance)
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.cinder.name
    endpoint = "image-service"
  }

  application {
    name     = data.juju_application.glance[0].name
    endpoint = "image-service"
  }
}
