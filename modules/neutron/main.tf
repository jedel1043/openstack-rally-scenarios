terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

resource "juju_application" "mysql-router" {
  name = "neutron-api-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_application" "neutron-api" {
  name = "neutron-api"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "neutron-api"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=2G"

  config = merge(
    {
      debug                             = false
      verbose                           = false
      neutron-security-groups           = true
      flat-network-providers            = "physnet1"
      enable-ml2-port-security          = true
      openstack-origin                  = "distro"
      global-physnet-mtu                = 1500
      physical-network-mtus             = "physnet1:1500"
      manage-neutron-plugin-legacy-mode = false
      enable-ml2-dns                    = true
      dns-domain                        = var.dns_domain
      vip                               = var.vip
    },
    var.neutron_api_options
  )
}

resource "juju_application" "hacluster" {
  name = "neutron-api-hacluster"

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

resource "juju_application" "neutron-ovn" {
  name = "neutron-api-plugin-ovn"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "neutron-api-plugin-ovn"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  config = {
    dns-servers = join(" ", var.dns_servers)
  }
}

resource "juju_application" "ovn-central" {
  name = "ovn-central"

  model_uuid = data.juju_model.openstack.uuid

  units       = 3
  constraints = "mem=2G"

  charm {
    name    = "ovn-central"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  config = {
    source = "distro"
  }
}

# Move into nova-compute when testing it
# resource "juju_application" "ovn-chassis" {
#   name = "ovn-chassis"

#   model_uuid = data.juju_model.openstack.uuid

#   charm {
#     name    = "ovn-chassis"
#     channel = "latest/edge"
#     base    = "ubuntu@24.04"
#   }

#   config = {
#     debug                     = false
#     ovn-bridge-mappings       = "physnet1:br-data"
#     prefer-chassis-as-gw      = true
#   }
# }

output "app_name" {
  description = "Name of the Neutron API application"
  value       = juju_application.neutron-api.name
}