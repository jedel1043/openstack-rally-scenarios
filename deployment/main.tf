variable "keystone_vip" {
  description = "Virtual IP for the Keystone service"
  type        = string
  default     = false
  nullable    = false
}

variable "glance_vip" {
  description = "Virtual IP for the Glance service"
  type        = string
  default     = ""
  nullable    = false
}

variable "designate_vip" {
  description = "Virtual IP for the Designate service"
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition     = var.designate_vip == "" || var.neutron_vip != ""
    error_message = "Designate service requires enabling the Neutron API service."
  }
}

variable "neutron_vip" {
  description = "Virtual IP for the Neutron service"
  type        = string
  default     = ""
  nullable    = false
}

variable "placement_vip" {
  description = "Virtual IP for the Placement service"
  type        = string
  default     = ""
  nullable    = false
}

variable "cinder_vip" {
  description = "Virtual IP for the Cinder service"
  type        = string
  default     = ""
  nullable    = false
}

variable "nova_vip" {
  description = "Virtual IP for the Nova Cloud Controller service"
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition = var.nova_vip == "" || (
      var.glance_vip != "" &&
      var.placement_vip != "" &&
      var.cinder_vip != "" &&
      var.neutron_vip != ""
    )
    error_message = "Nova service requires enabling the Glance, Placement, Cinder and Neutron services."
  }
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

variable "use_lxd" {
  description = "Use LXD containers to emplace the services"
  type        = bool
  default     = false
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
  dns_domain     = "openstack.qa.1ss."
  designate      = var.designate_vip != ""
  glance         = var.glance_vip != ""
  neutron        = var.neutron_vip != ""
  placement      = var.placement_vip != ""
  nova           = var.nova_vip != ""
  cinder         = var.cinder_vip != ""
  ceph           = local.glance || local.cinder || local.nova
  rabbitmq       = local.neutron || local.nova || local.cinder
  certificates   = local.neutron || local.nova
  memcached      = local.designate || local.nova
  unit_placement = [for machine in juju_machine.os-machines : "lxd:${machine.machine_id}"]
}

locals {
  certificates_info = length(juju_application.vault) > 0 ? {
    name     = juju_application.vault[0].name
    endpoint = "certificates"
  } : null
}

module "keystone" {
  source         = "../modules/keystone"
  model_uuid     = juju_model.openstack.uuid
  mysql          = juju_application.mysql.name
  certificates   = local.certificates_info
  vip            = var.keystone_vip
  unit_placement = local.unit_placement
}

module "ceph" {
  count      = local.ceph ? 1 : 0
  source     = "../modules/ceph"
  model_uuid = juju_model.openstack.uuid
}

module "glance" {
  count          = local.glance ? 1 : 0
  source         = "../modules/glance"
  model_uuid     = juju_model.openstack.uuid
  keystone       = module.keystone.app_name
  mysql          = juju_application.mysql.name
  ceph           = module.ceph[0].app_name
  certificates   = local.certificates_info
  vip            = var.glance_vip
  unit_placement = local.unit_placement
  rabbitmq       = length(juju_application.rabbitmq) > 0 ? juju_application.rabbitmq[0].name : null
}

module "neutron" {
  count      = local.neutron ? 1 : 0
  source     = "../modules/neutron"
  model_uuid = juju_model.openstack.uuid
  keystone   = module.keystone.app_name
  mysql      = juju_application.mysql.name
  rabbitmq   = juju_application.rabbitmq[0].name
  neutron_api_options = local.designate ? {
    reverse-dns-lookup = true
  } : {}
  dns_domain     = local.dns_domain
  dns_servers    = local.dns_servers
  certificates   = local.certificates_info
  vip            = var.neutron_vip
  unit_placement = local.unit_placement
}

module "designate" {
  count          = local.designate ? 1 : 0
  source         = "../modules/designate"
  model_uuid     = juju_model.openstack.uuid
  keystone       = module.keystone.app_name
  mysql          = juju_application.mysql.name
  rabbitmq       = juju_application.rabbitmq[0].name
  memcached      = juju_application.memcached[0].name
  neutron_api    = module.neutron[0].neutron-api
  dns_domain     = local.dns_domain
  forwarders     = local.dns_servers
  certificates   = local.certificates_info
  vip            = var.designate_vip
  unit_placement = local.unit_placement
}

module "placement" {
  count          = local.placement ? 1 : 0
  source         = "../modules/placement"
  model_uuid     = juju_model.openstack.uuid
  keystone       = module.keystone.app_name
  mysql          = juju_application.mysql.name
  certificates   = local.certificates_info
  vip            = var.placement_vip
  unit_placement = local.unit_placement
}

module "cinder" {
  count          = local.cinder ? 1 : 0
  source         = "../modules/cinder"
  model_uuid     = juju_model.openstack.uuid
  keystone       = module.keystone.app_name
  mysql          = juju_application.mysql.name
  rabbitmq       = juju_application.rabbitmq[0].name
  certificates   = local.certificates_info
  vip            = var.placement_vip
  unit_placement = local.unit_placement
  ceph           = module.ceph[0].app_name
  glance         = length(module.glance) > 0 ? module.glance[0].app_name : null
}

module "nova" {
  count          = local.nova ? 1 : 0
  source         = "../modules/nova"
  model_uuid     = juju_model.openstack.uuid
  keystone       = module.keystone.app_name
  mysql          = juju_application.mysql.name
  rabbitmq       = juju_application.rabbitmq[0].name
  memcached      = juju_application.memcached[0].name
  ceph           = module.ceph[0].app_name
  glance         = module.glance[0].app_name
  placement      = module.placement[0].app_name
  cinder         = module.cinder[0].cinder
  cinder_ceph    = module.cinder[0].cinder-ceph
  neutron_api    = length(module.neutron) > 0 ? module.neutron[0].neutron-api : null
  ovn_central    = length(module.neutron) > 0 ? module.neutron[0].ovn-central : null
  certificates   = local.certificates_info
  vip            = var.nova_vip
  unit_placement = local.unit_placement
}
