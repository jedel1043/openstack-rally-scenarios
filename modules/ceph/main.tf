variable "model_uuid" {
  description = "Model UUID where all applications will be deployed"
  type        = string
  nullable    = false
}

terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

data "juju_model" "openstack" {
  uuid = var.model_uuid
}

resource "juju_application" "ceph-mon" {
  name = "ceph-mon"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "ceph-mon"
    channel = "squid/edge"
    base    = "ubuntu@24.04"
  }

  units = 1

  constraints = "mem=2G"

  config = {
    source             = "distro"
    loglevel           = 1
    monitor-count      = 1
    expected-osd-count = 3
  }
}

resource "juju_application" "ceph-osd" {
  name = "ceph-osd"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "ceph-osd"
    channel = "squid/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=2G"

  config = {
    source      = "distro"
    loglevel    = 1
    osd-devices = ""
    config-flags = jsonencode({
      osd = {
        "osd memory target" = 1073741824
      }
    })
  }

  storage_directives = {
    osd-devices = "cinder,1,10G"
  }
}

resource "juju_integration" "osd-to-mon" {
  model_uuid = data.juju_model.openstack.uuid

  application {
    name     = juju_application.ceph-mon.name
    endpoint = "osd"
  }

  application {
    name     = juju_application.ceph-osd.name
    endpoint = "mon"
  }
}

output "app_name" {
  description = "Name of the application offering Ceph to clients"
  value       = juju_application.ceph-mon.name
}
