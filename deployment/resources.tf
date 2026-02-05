resource "juju_model" "openstack" {
  name = "openstack"
}

resource "juju_application" "mysql" {
  name       = "mysql"
  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "mysql-innodb-cluster"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
  units       = 3
  constraints = "mem=4G"
  config = {
    innodb-buffer-pool-size = "50%"
    max-connections         = 20000
    tuning-level            = "fast"
  }
}

resource "juju_application" "rabbitmq" {
  count      = local.rabbitmq ? 1 : 0
  name       = "rabbitmq-server"
  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "rabbitmq-server"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
  units       = 3
  constraints = "mem=1G"
  config = {
    min-cluster-size = 1
  }
}

resource "juju_application" "memcached" {
  count      = local.designate ? 1 : 0
  name       = "memcached"
  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "memcached"
    channel = "latest/stable"
    base    = "ubuntu@22.04"
  }
  units       = 2
  constraints = "mem=2G"
}

resource "juju_application" "vault" {
  count      = local.certificates ? 1 : 0
  name       = "vault"
  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "vault"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
  units = 1

  config = {
    auto-generate-root-ca-cert = true
  }
}

resource "juju_integration" "rabbitmq-certificates" {
  count      = local.rabbitmq && local.certificates_info != null ? 1 : 0
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.rabbitmq[0].name
    endpoint = "certificates"
  }

  application {
    name     = local.certificates_info.name
    endpoint = local.certificates_info.endpoint
  }
}

resource "juju_application" "vault-mysql-router" {
  count = length(juju_application.vault)
  name  = "vault-mysql-router"

  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_integration" "vault-shared-db" {
  count      = length(juju_application.vault)
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.vault[0].name
    endpoint = "shared-db"
  }

  application {
    name     = juju_application.vault-mysql-router[0].name
    endpoint = "shared-db"
  }
}

resource "juju_integration" "vault-db-router" {
  count      = length(juju_application.vault-mysql-router)
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.mysql.name
    endpoint = "db-router"
  }

  application {
    name     = juju_application.vault-mysql-router[0].name
    endpoint = "db-router"
  }
}
