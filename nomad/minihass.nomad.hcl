job "minihass" {
  datacenters = ["dc1"]

  group "smart-home" {
    network {
      mode = "host"
      port "http" {
        to = 5000
      }
    }

    service {
      name = "minihass"
      port = "http"
      
      check {
        type     = "http"
        path     = "/health"
        interval = "30s"
        timeout  = "5s"
      }
    }

    task "app" {
      driver = "docker"

      config {
        image = "ghcr.io/sstent/minihass:801eb6050ce38966d35cc9a0c070714a8ecf5c78"
        ports = ["http"]
      }

      env {
        CONSUL_HOST = "consul.service.dc1.consul"
        CONSUL_PORT = "8500"
      }

      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}