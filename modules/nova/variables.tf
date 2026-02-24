variable "model_uuid" {
  description = "Model UUID where all applications will be deployed"
  type        = string
  nullable    = false
}

variable "vip" {
  description = "Virtual IP to use to front the Glance API service."
  type        = string
  nullable    = false
  validation {
    condition     = var.vip != ""
    error_message = "Virtual IP must not be empty."
  }
}

variable "mysql" {
  description = "Name of the MySQL application"
  type        = string
  nullable    = false
}

variable "rabbitmq" {
  description = "Name of the RabbitMQ application"
  type        = string
  nullable    = false
}

variable "memcached" {
  description = "Name of the Memcached application"
  type        = string
  nullable    = false
}

variable "keystone" {
  description = "Name of the Keystone application"
  type        = string
  nullable    = false
}

variable "glance" {
  description = "Name of the Glance application"
  type        = string
  nullable    = false
}

variable "placement" {
  description = "Name of the Placement application"
  type        = string
  nullable    = false
}

variable "cinder" {
  description = "Name of the Cinder application"
  type        = string
  nullable    = false
}

variable "ceph" {
  description = "Name of the Ceph application for Ceph clients"
  type        = string
  nullable    = false
}

variable "cinder_ceph" {
  description = "Name of the Cinder Ceph application"
  type        = string
  nullable    = false
}

variable "neutron_api" {
  description = "Name of the Neutron API application"
  type        = string
  nullable    = true
  default     = null
}

variable "ovn_central" {
  description = "Name of the OVN Central application"
  type        = string
  nullable    = true
  default     = null
}

variable "certificates" {
  description = "Name and endpoint of the SSL certificates application"
  type = object({
    name     = string
    endpoint = string
  })
  nullable = true
  default  = null

  validation {
    condition = (
      var.certificates == null || (
        length(trimspace(var.certificates.name)) > 0 &&
        length(trimspace(var.certificates.endpoint)) > 0
      )
    )
    error_message = "Name and endpoint for the certificates application must not be empty."
  }
}

variable "unit_placement" {
  description = "Information about where to place the service's units in the cloud."
  type        = list(string)
  nullable    = false
  default     = []
}
