resource "juju_integration" "identity-service" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.designate.name
    endpoint = "identity-service"
  }

  application {
    name     = data.juju_application.keystone.name
    endpoint = "identity-service"
  }
}

resource "juju_integration" "certificates" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.designate.name
    endpoint = "certificates"
  }

  application {
    name     = data.juju_application.certificates.name
    endpoint = var.certificates.endpoint
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
    name     = juju_application.designate.name
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
    name     = juju_application.designate.name
    endpoint = "amqp"
  }

  application {
    name     = data.juju_application.rabbitmq.name
    endpoint = "amqp"
  }
}

resource "juju_integration" "dns-backend" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.designate.name
    endpoint = "dns-backend"
  }

  application {
    name     = juju_application.designate-bind.name
    endpoint = "dns-backend"
  }
}

resource "juju_integration" "coordinator-memcached" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.designate.name
    endpoint = "coordinator-memcached"
  }

  application {
    name     = data.juju_application.memcached.name
    endpoint = "cache"
  }
}

resource "juju_integration" "dnsaas" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.designate.name
    endpoint = "dnsaas"
  }

  application {
    name     = data.juju_application.neutron_api.name
    endpoint = "external-dns"
  }
}

resource "juju_integration" "ha" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.designate.name
    endpoint = "ha"
  }

  application {
    name     = juju_application.hacluster.name
    endpoint = "ha"
  }
}
