data "juju_model" "openstack" {
  uuid = var.model_uuid
}

data "juju_application" "certificates" {
  count      = var.certificates != null ? 1 : 0
  name       = var.certificates.name
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "keystone" {
  name       = var.keystone
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "mysql" {
  name       = var.mysql
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "ceph" {
  name       = var.ceph
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "rabbitmq" {
  name       = var.rabbitmq
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "glance" {
  count      = var.glance != null ? 1 : 0
  name       = var.glance
  model_uuid = data.juju_model.openstack.uuid
}