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

resource "juju_application" "designate" {
  name = "designate"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "designate"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=1G"

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

resource "juju_application" "designate-bind" {
  name = "designate-bind"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "designate-bind"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 2

  constraints = "mem=1G"

  config = {
    forwarders = join(";", var.forwarders)
  }
}
