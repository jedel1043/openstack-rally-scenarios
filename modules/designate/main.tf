terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

locals {
  dns-forwarder = coalesce(var.upstream_dns_server, data.external.local_upstream_dns.result.server-ip)
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
      condition     = local.dns-forwarder != ""
      error_message = "DNS forwarder hostname must not be empty."
    }
  }


  charm {
    name    = "designate-bind"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 2

  constraints = "mem=1G"

  config = {
    forwarders = local.dns-forwarder
  }
}
