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

terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

provider "juju" {}

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
  count      = var.designate ? 1 : 0
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
  count      = var.designate ? 1 : 0
  name       = "memcached"
  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "memcached"
    channel = "latest/stable"
    base    = "ubuntu@24.04"
  }
  units       = 2
  constraints = "mem=2G"
}

module "keystone" {
  source     = "../modules/keystone"
  model_uuid = juju_model.openstack.uuid
  mysql      = juju_application.mysql.name
}

module "ceph" {
  count      = var.glance ? 1 : 0
  source     = "../modules/ceph"
  model_uuid = juju_model.openstack.uuid
}

module "glance" {
  count      = var.glance ? 1 : 0
  source     = "../modules/glance"
  model_uuid = juju_model.openstack.uuid
  keystone   = module.keystone.app_name
  mysql      = juju_application.mysql.name
  ceph       = module.ceph[0].app_name
}

module "designate" {
  count      = var.designate ? 1 : 0
  source     = "../modules/designate"
  model_uuid = juju_model.openstack.uuid
  keystone   = module.keystone.app_name
  mysql      = juju_application.mysql.name
  rabbitmq   = juju_application.rabbitmq[0].name
  memcached  = juju_application.memcached[0].name
}
