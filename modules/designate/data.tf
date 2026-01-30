data "juju_model" "openstack" {
  uuid = var.model_uuid
}

data "juju_application" "certificates" {
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

data "juju_application" "rabbitmq" {
  name       = var.rabbitmq
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "memcached" {
  name       = var.memcached
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "neutron_api" {
  name       = var.neutron_api
  model_uuid = data.juju_model.openstack.uuid
}
