terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

locals {
  dns-forwarders = coalescelist(
    var.upstream_dns_servers,
    jsondecode(
      data.external.local_upstream_dns.result.servers
    )
  )
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
    nameservers = "ns1.openstack.qa.1ss."
  }
}

resource "juju_application" "designate-bind" {
  name = "designate-bind"

  lifecycle {
    precondition {
      condition     = length(local.dns-forwarders) > 0
      error_message = "Must specify at least one DNS forwarder server."
    }
  }

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "designate-bind"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 2

  constraints = "mem=1G"

  config = {
    forwarders = join(";", local.dns-forwarders)
  }
}
