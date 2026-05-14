# AWS deployment

For when one VPS isn't enough — multi-region, auto-scaling, or
compliance reasons.

## Architecture

| Layer | AWS service |
|---|---|
| Static channel | **S3** + **CloudFront**. Upload `installer.py`, `install.sh`, `install.ps1`, `registry.json` to a bucket; serve via CDN. No container needed for the static side. |
| API (Phase M) | **ECS Fargate** running `Dockerfile.api`. Behind an **Application Load Balancer** with **ACM**-issued TLS. |
| Database | **RDS** Postgres 17. Multi-AZ for prod. |
| Cache / queue | **ElastiCache** Redis 7. |
| Secrets | **Secrets Manager**. The Laravel admin reads its DB password + Sanctum secret from there. |
| DNS | **Route 53** with A/AAAA records to CloudFront + ALB. |
| Observability | **CloudWatch Logs** for container stdout; **CloudWatch Metrics** + alarms for ALB 5xx + RDS connections. |

## Static-only quick recipe

```bash
# 1. Build artefacts locally
python3 scripts/bundle.py

# 2. Sync to S3
aws s3 sync ./dist                            s3://get.simtabi.com/
aws s3 sync ./bootstrap                       s3://get.simtabi.com/
aws s3 cp   ./registry.json                   s3://get.simtabi.com/
aws s3 cp   ./schemas/registry.schema.json    s3://get.simtabi.com/schemas/

# 3. Invalidate CloudFront cache for moving aliases
aws cloudfront create-invalidation \
    --distribution-id <DIST_ID> \
    --paths '/install.sh' '/install.ps1' '/installer.py' \
            '/installer.py.sha256' '/registry.json'
```

Pin immutable per-version paths (`/<product>/<version>/...`) with
`Cache-Control: public, immutable, max-age=31536000` and they never
need invalidation.

## Permissions

The IAM policy for the publish role only needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::get.simtabi.com/*"
    },
    {
      "Effect": "Allow",
      "Action": "cloudfront:CreateInvalidation",
      "Resource": "arn:aws:cloudfront::ACCOUNT:distribution/DIST_ID"
    }
  ]
}
```

Wire it up via GitHub Actions OIDC (no static AWS keys in CI).

## Full-stack (API + admin) recipe

See [`Dockerfile.api`](../Dockerfile.api) (coming in Phase M). The ECS
task definition + Terraform / CDK examples will live in the
`get-installer-admin` sibling repo to keep this repo
infrastructure-agnostic.

## Cost ballpark

| Service | ~Monthly |
|---|---|
| S3 + CloudFront for the static channel (10 GB transfer/mo) | ~$2 |
| ECS Fargate 0.25 vCPU / 0.5 GB always-on | ~$10 |
| RDS Postgres `t4g.micro` | ~$15 |
| ElastiCache Redis `cache.t4g.micro` | ~$12 |
| ALB | ~$18 |
| **Total ballpark for the dynamic API stack** | **~$60/mo** |

Static-only is essentially free.
