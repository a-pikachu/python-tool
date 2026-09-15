docker exec -i openclaw_postgres psql -U openclaw -d openclaw -c "select * from canadian_tire_restocks order by current_time desc;"
