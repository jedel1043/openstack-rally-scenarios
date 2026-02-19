resource "juju_model" "openstack" {
  name = "openstack"
}

resource "juju_machine" "os-machines" {
  count = var.use_lxd ? 3 : 0

  model_uuid  = juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "os-machine-${count.index}"
  constraints = "mem=16G"

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_machine" "mysql" {
  count       = 3
  model_uuid  = juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "mysql-m${count.index}"
  constraints = "mem=4G"

  placement = try("lxd:${juju_machine.os-machines[count.index]}", null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_application" "mysql" {
  name       = "mysql"
  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "mysql-innodb-cluster"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  machines = toset(juju_machine.mysql[*].machine_id)

  config = {
    innodb-buffer-pool-size = "50%"
    max-connections         = 20000
    tuning-level            = "fast"
  }
}

resource "juju_machine" "rabbitmq" {
  count       = 3
  model_uuid  = juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "rabbitmq-m${count.index}"
  constraints = "mem=1G"

  placement = try("lxd:${juju_machine.os-machines[count.index]}", null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
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

  machines = toset(juju_machine.rabbitmq[*].machine_id)

  config = {
    min-cluster-size = 1
  }
}

resource "juju_machine" "memcached" {
  count       = 2
  model_uuid  = juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "memcached-m${count.index}"
  constraints = "mem=2G"

  placement = try("lxd:${juju_machine.os-machines[count.index]}", null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
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

  machines = toset(juju_machine.memcached[*].machine_id)
}

resource "juju_machine" "vault" {
  count      = 1
  model_uuid = juju_model.openstack.uuid
  base       = "ubuntu@24.04"
  name       = "vault-m${count.index}"

  placement = try("lxd:${juju_machine.os-machines[count.index]}", null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
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

  machines = toset(juju_machine.vault[*].machine_id)

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
