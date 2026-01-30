variable "glance" {
  description = "Deploy Glance service"
  type        = bool
  default     = false
  nullable    = false
}

variable "designate" {
  description = "Deploy Designate service"
  type        = bool
  default     = false
  nullable    = false
}

variable "neutron" {
  description = "Deploy Neutron service"
  type        = bool
  default     = false
  nullable    = false
}

variable "upstream_dns_servers" {
  description = "Designate BIND upstream DNS servers to forward requests to"
  type        = list(string)
  default     = []
  validation {
    condition = alltrue([
      for hostname in var.upstream_dns_servers : can(cidrhost(hostname, 0))
    ])
    error_message = "Upstream DNS server IP addresses must be valid."
  }
}

terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

provider "juju" {}

data "external" "local_upstream_dns" {
  program = ["/bin/bash", "-c", <<EOF
      if command -v systemd-resolve > /dev/null; then
          servers=$(systemd-resolve --status 2> /dev/null | sed --regexp-extended 's/\s*DNS Servers:\s+([[:digit:]]+)/\1/g;t;d'| head -n 1)
      else
          servers=$(resolvectl 2> /dev/null | sed --regexp-extended 's/\s*Current DNS Server:\s+([[:digit:]]+)/\1/g;t;d')
      fi
      jq -Rsc '. / "\n" - [""] | tostring | {servers: .}' <<< $servers
    EOF
  ]
}

locals {
  dns_servers = coalescelist(
    var.upstream_dns_servers,
    jsondecode(data.external.local_upstream_dns.result.servers)
  )
  dns_domain   = "openstack.qa.1ss."
  neutron      = var.neutron || var.designate
  rabbitmq     = local.neutron
  certificates = local.neutron
}

locals {
  certificates_info = length(juju_application.vault) > 0 ? {
    name     = juju_application.vault[0].name
    endpoint = "certificates"
  } : null
}

module "keystone" {
  source     = "../modules/keystone"
  model_uuid = juju_model.openstack.uuid
  mysql      = juju_application.mysql.name

  certificates = local.certificates_info
}

module "ceph" {
  count      = var.glance ? 1 : 0
  source     = "../modules/ceph"
  model_uuid = juju_model.openstack.uuid
}

module "glance" {
  count        = var.glance ? 1 : 0
  source       = "../modules/glance"
  model_uuid   = juju_model.openstack.uuid
  keystone     = module.keystone.app_name
  mysql        = juju_application.mysql.name
  ceph         = module.ceph[0].app_name
  certificates = local.certificates_info
}

module "neutron" {
  count      = local.neutron ? 1 : 0
  source     = "../modules/neutron"
  model_uuid = juju_model.openstack.uuid
  keystone   = module.keystone.app_name
  mysql      = juju_application.mysql.name
  rabbitmq   = juju_application.rabbitmq[0].name
  neutron_api_options = var.designate ? {
    reverse-dns-lookup = true
  } : {}
  dns_domain   = local.dns_domain
  dns_servers  = local.dns_servers
  certificates = local.certificates_info
}

module "designate" {
  count        = var.designate ? 1 : 0
  source       = "../modules/designate"
  model_uuid   = juju_model.openstack.uuid
  keystone     = module.keystone.app_name
  mysql        = juju_application.mysql.name
  rabbitmq     = juju_application.rabbitmq[0].name
  memcached    = juju_application.memcached[0].name
  neutron_api  = module.neutron[0].app_name
  dns_domain   = local.dns_domain
  forwarders   = local.dns_servers
  certificates = local.certificates_info
}
