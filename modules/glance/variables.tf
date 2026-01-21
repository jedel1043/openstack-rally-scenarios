variable "model_uuid" {
  description = "Model UUID where all applications will be deployed"
  type        = string
  nullable    = false
}

variable "mysql" {
  description = "Name of the MySQL application"
  type        = string
  nullable    = false
}

variable "keystone" {
  description = "Name of the Keystone application"
  type        = string
  nullable    = false
}

variable "ceph" {
  description = "Name of the Ceph application for Ceph clients"
  type        = string
  nullable    = false
}
