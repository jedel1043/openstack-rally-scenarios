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
