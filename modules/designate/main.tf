terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

resource "juju_application" "mysql-router" {
  name = "designate-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_machine" "designate" {
  count       = 3
  model_uuid  = data.juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "designate-m${count.index}"
  constraints = "mem=1G"

  placement = try(var.unit_placement[count.index], null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_application" "designate" {
  name = "designate"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "designate"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  machines = toset(juju_machine.designate[*].machine_id)

  config = {
    debug       = false
    verbose     = false
    nameservers = "ns1.${var.dns_domain}"
    vip         = var.vip
  }
}

resource "juju_application" "hacluster" {
  name = "designate-hacluster"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "hacluster"
    channel = "2.4/edge"
    base    = "ubuntu@24.04"
  }

  config = {
    cluster_count = 3
  }
}

resource "juju_machine" "designate-bind" {
  count       = 2
  model_uuid  = data.juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "designate-bind-m${count.index}"
  constraints = "mem=1G"

  placement = try(var.unit_placement[count.index], null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_application" "designate-bind" {
  name = "designate-bind"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "designate-bind"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }


  machines = toset(juju_machine.designate-bind[*].machine_id)

  config = {
    forwarders = join(";", var.forwarders)
  }
}
