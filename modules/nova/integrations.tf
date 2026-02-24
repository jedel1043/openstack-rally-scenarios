resource "juju_integration" "cloud-compute" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "cloud-compute"
  }

  application {
    name     = juju_application.nova-compute.name
    endpoint = "cloud-compute"
  }
}

resource "juju_integration" "identity-service" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "identity-service"
  }

  application {
    name     = data.juju_application.keystone.name
    endpoint = "identity-service"
  }
}

resource "juju_integration" "nova-compute-image-service" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-compute.name
    endpoint = "image-service"
  }

  application {
    name     = data.juju_application.glance.name
    endpoint = "image-service"
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
    name     = juju_application.nova-cloud-controller.name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.mysql-router.name
    endpoint = "shared-db"
  }
}

resource "juju_integration" "ha" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
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
    name     = juju_application.nova-cloud-controller.name
    endpoint = "amqp"
  }

  application {
    name     = data.juju_application.rabbitmq.name
    endpoint = "amqp"
  }
}

resource "juju_integration" "nova-compute-amqp" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-compute.name
    endpoint = "amqp"
  }

  application {
    name     = data.juju_application.rabbitmq.name
    endpoint = "amqp"
  }
}

resource "juju_integration" "memcache" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "memcache"
  }

  application {
    name     = data.juju_application.memcached.name
    endpoint = "cache"
  }
}

resource "juju_integration" "ceph" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-compute.name
    endpoint = "ceph"
  }

  application {
    name     = data.juju_application.ceph.name
    endpoint = "client"
  }
}

resource "juju_integration" "ceph-access" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-compute.name
    endpoint = "ceph-access"
  }

  application {
    name     = data.juju_application.cinder-ceph.name
    endpoint = "ceph-access"
  }
}

resource "juju_integration" "cinder-volume-service" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "cinder-volume-service"
  }

  application {
    name     = data.juju_application.cinder.name
    endpoint = "cinder-volume-service"
  }
}

resource "juju_integration" "certificates" {
  count      = length(data.juju_application.certificates)
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "certificates"
  }

  application {
    name     = data.juju_application.certificates[0].name
    endpoint = var.certificates.endpoint
  }
}

resource "juju_integration" "image-service" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "image-service"
  }

  application {
    name     = data.juju_application.glance.name
    endpoint = "image-service"
  }
}


resource "juju_integration" "placement" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "placement"
  }

  application {
    name     = data.juju_application.placement.name
    endpoint = "placement"
  }
}

resource "juju_integration" "neutron-api" {
  count      = length(data.juju_application.neutron_api)
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.nova-cloud-controller.name
    endpoint = "neutron-api"
  }

  application {
    name     = data.juju_application.neutron_api[0].name
    endpoint = "neutron-api"
  }
}

