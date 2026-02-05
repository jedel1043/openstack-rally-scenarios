resource "juju_integration" "identity-service" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.neutron-api.name
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
    name     = juju_application.neutron-api.name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.mysql-router.name
    endpoint = "shared-db"
  }
}

resource "juju_integration" "amqp" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.neutron-api.name
    endpoint = "amqp"
  }

  application {
    name     = data.juju_application.rabbitmq.name
    endpoint = "amqp"
  }
}

resource "juju_integration" "neutron-plugin" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.neutron-ovn.name
    endpoint = "neutron-plugin"
  }

  application {
    name     = juju_application.neutron-api.name
    endpoint = "neutron-plugin-api-subordinate"
  }
}

resource "juju_integration" "ovsdb-cms" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.neutron-ovn.name
    endpoint = "ovsdb-cms"
  }

  application {
    name     = juju_application.ovn-central.name
    endpoint = "ovsdb-cms"
  }
}

resource "juju_integration" "neutron-api-certificates" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.neutron-api.name
    endpoint = "certificates"
  }

  application {
    name     = data.juju_application.certificates.name
    endpoint = var.certificates.endpoint
  }
}

resource "juju_integration" "neutron-ovn-certificates" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.neutron-ovn.name
    endpoint = "certificates"
  }

  application {
    name     = data.juju_application.certificates.name
    endpoint = var.certificates.endpoint
  }
}

resource "juju_integration" "ovn-central-certificates" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.ovn-central.name
    endpoint = "certificates"
  }

  application {
    name     = data.juju_application.certificates.name
    endpoint = var.certificates.endpoint
  }
}

resource "juju_integration" "ha" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.neutron-api.name
    endpoint = "ha"
  }

  application {
    name     = juju_application.hacluster.name
    endpoint = "ha"
  }
}

# Move into nova-compute when testing it
# resource "juju_integration" "ovsdb" {
#   model_uuid = data.juju_model.openstack.uuid

#   application {
#     name     = juju_application.ovn-chassis.name
#     endpoint = "ovsdb"
#   }

#   application {
#     name     = juju_application.ovn-central.name
#     endpoint = "ovsdb"
#   }
# }
