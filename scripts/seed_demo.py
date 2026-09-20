"""End-to-end demo script for the SWMS Drop 1 backend.

Run the API first (uvicorn app.main:app --reload), then:
    PYTHONPATH=. python3 scripts/seed_demo.py
"""

import asyncio
import sys
import httpx

BASE_URL = "http://localhost:8000"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        print("1. Registering planner user...")
        register_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "planner.shirva@example.com",
                "password": "SecurePass123!",
                "full_name": "Shirva Planner",
                "role": "ADMIN",  # deliberately ignored by the backend
            },
        )
        if register_resp.status_code not in (201, 409):
            print(register_resp.text)
            sys.exit(1)
        registered = register_resp.json()
        if register_resp.status_code == 201:
            assert registered["data"]["role"] == "RESEARCHER", "self-registration must force RESEARCHER"
            print("   -> registered as RESEARCHER (role escalation ignored, as required)")
        else:
            print("   -> user already exists, continuing")

        print("2. Logging in...")
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "planner.shirva@example.com", "password": "SecurePass123!"},
        )
        login_resp.raise_for_status()
        access_token = login_resp.json()["data"]["access_token"]
        auth_headers = {"Authorization": f"Bearer {access_token}"}
        print("   -> got access token")

        me_resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        me_resp.raise_for_status()
        role = me_resp.json()["data"]["role"]
        print(f"   -> current role is {role}")
        if role not in ("ADMIN", "PLANNER"):
            print("   -> role is not ADMIN/PLANNER yet. Promoting to PLANNER...")
            try:
                from scripts.bootstrap_admin import main as bootstrap_main
                await bootstrap_main("planner.shirva@example.com", "PLANNER")
                # Re-login to obtain token with updated role
                login_resp = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "planner.shirva@example.com", "password": "SecurePass123!"},
                )
                login_resp.raise_for_status()
                access_token = login_resp.json()["data"]["access_token"]
                auth_headers = {"Authorization": f"Bearer {access_token}"}
                me_resp = await client.get("/api/v1/auth/me", headers=auth_headers)
                me_resp.raise_for_status()
                role = me_resp.json()["data"]["role"]
                print(f"   -> successfully promoted; current role is now {role}")
            except Exception as exc:
                print(
                    f"   -> auto-promotion failed ({exc}). Run:\n"
                    "      python3 -m scripts.bootstrap_admin planner.shirva@example.com PLANNER\n"
                    "      then re-run this script."
                )
                sys.exit(1)

        print("3. Creating habitation 'Shirva'...")
        habitation_resp = await client.post(
            "/api/v1/habitations",
            headers=auth_headers,
            json={
                "name": "Shirva",
                "habitation_type": "VILLAGE",
                "state": "Karnataka",
                "district": "Udupi",
                "boundary_geojson": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [74.79, 13.34],
                                [74.81, 13.34],
                                [74.81, 13.36],
                                [74.79, 13.36],
                                [74.79, 13.34],
                            ]
                        ]
                    ],
                },
            },
        )
        if habitation_resp.status_code == 409:
            print("   -> habitation already exists, fetching it instead")
            list_resp = await client.get("/api/v1/habitations", headers=auth_headers)
            habitation = next(h for h in list_resp.json()["data"] if h["name"] == "Shirva")
        else:
            habitation_resp.raise_for_status()
            habitation = habitation_resp.json()["data"]
        habitation_id = habitation["id"]
        print(f"   -> habitation id {habitation_id}, area {habitation.get('area_sqkm')} sqkm")

        print("4. Opening a DRAFT parameter set...")
        ps_resp = await client.post(
            f"/api/v1/habitations/{habitation_id}/parameter-sets",
            headers=auth_headers,
            json={"change_note": "initial demo version"},
        )
        ps_resp.raise_for_status()
        psid = ps_resp.json()["data"]["id"]
        print(f"   -> parameter set {psid} version {ps_resp.json()['data']['version_no']}")

        print("5. Filling demography with an OUT-OF-RANGE growth rate (14%)...")
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/demography",
            headers=auth_headers,
            json={
                "population": 22500,
                "annual_growth_rate_pct": 14.0,  # Deliberate failure
                "household_size_avg": 4.2,
                "floating_population_pct": 5.0,
            },
        )).raise_for_status()
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/community_infrastructure",
            headers=auth_headers,
            json={
                "road_network_km": 42.0,
                "collection_vehicles_count": 3,
                "collection_coverage_pct": 80.0,
                "treatment_capacity_tpd": 5.0,
                "landfill_capacity_tonnes": 50000.0,
                "landfill_remaining_tonnes": 12000.0,
            },
        )).raise_for_status()
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/industrial_activities",
            headers=auth_headers,
            json={"industrial_waste_tpd": 2.0},
        )).raise_for_status()
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/natural_resources",
            headers=auth_headers,
            json={"annual_rainfall_mm": 3200.0},
        )).raise_for_status()
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/terrain",
            headers=auth_headers,
            json={"avg_slope_pct": 4.0},
        )).raise_for_status()
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/economic_conditions",
            headers=auth_headers,
            json={"swm_annual_budget": 2500000.0},
        )).raise_for_status()
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/cultural_context",
            headers=auth_headers,
            json={"segregation_practice_pct": 35.0},
        )).raise_for_status()
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/waste-baseline",
            headers=auth_headers,
            json={
                "per_capita_generation_kg_day": 0.45,
                "composition": {
                    "organic": 55.0,
                    "plastic": 12.0,
                    "paper": 10.0,
                    "glass": 3.0,
                    "metal": 2.0,
                    "other": 18.0,
                },
            },
        )).raise_for_status()

        print("6. Validating (expecting FAIL on annual_growth_rate_pct)...")
        validate_resp = await client.post(
            f"/api/v1/parameter-sets/{psid}/validate", headers=auth_headers
        )
        validate_resp.raise_for_status()
        report = validate_resp.json()["data"]
        print(f"   -> result={report['result']} error_count={report['error_count']} completeness={report['completeness_pct']}%")
        for issue in report.get("issues", []):
            if issue.get("field_path") == "demography.annual_growth_rate_pct":
                print(f"   -> FOUND EXPECTED ISSUE: {issue.get('message')}")
        assert report["result"] == "FAIL", f"Expected FAIL in step 6, got {report['result']}"
        assert report["error_count"] == 1, f"Expected 1 error in step 6, got {report['error_count']}: {report.get('issues')}"

        print("7. Fixing the growth rate to 1.8%...")
        (await client.put(
            f"/api/v1/parameter-sets/{psid}/categories/demography",
            headers=auth_headers,
            json={
                "population": 22500,
                "annual_growth_rate_pct": 1.8,
                "household_size_avg": 4.2,
                "floating_population_pct": 5.0,
            },
        )).raise_for_status()

        print("8. Validating again (expecting PASS)...")
        validate_resp2 = await client.post(
            f"/api/v1/parameter-sets/{psid}/validate", headers=auth_headers
        )
        validate_resp2.raise_for_status()
        report2 = validate_resp2.json()["data"]
        print(f"   -> result={report2['result']} error_count={report2['error_count']} completeness={report2['completeness_pct']}%")
        assert report2["result"] == "PASS", f"Expected PASS in step 8, got {report2['result']}"
        assert report2["error_count"] == 0, f"Expected 0 errors in step 8, got {report2['error_count']}: {report2.get('issues')}"
        assert report2["completeness_pct"] == 100.0, f"Expected 100.0% completeness, got {report2['completeness_pct']}%"

        print("9. Committing to VALIDATED...")
        commit_resp = await client.post(
            f"/api/v1/parameter-sets/{psid}/commit", headers=auth_headers
        )
        commit_resp.raise_for_status()
        committed_data = commit_resp.json()["data"]
        print(f"   -> {committed_data}")
        assert committed_data["status"] == "VALIDATED", f"Expected VALIDATED, got {committed_data['status']}"

        habitation_after = await client.get(f"/api/v1/habitations/{habitation_id}", headers=auth_headers)
        habitation_after.raise_for_status()
        hab_data = habitation_after.json()["data"]
        print(f"   -> habitation status is now {hab_data['status']}")
        assert hab_data["status"] == "READY", f"Expected READY, got {hab_data['status']}"

        print("10. Uploading a GeoJSON road feature inside the boundary...")
        layer_resp = await client.post(
            f"/api/v1/habitations/{habitation_id}/layers",
            headers=auth_headers,
            json={
                "layer_name": "Shirva main road",
                "layer_type": "ROAD",
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "Main Street"},
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[74.795, 13.345], [74.805, 13.355]],
                            },
                        }
                    ],
                },
            },
        )
        if layer_resp.status_code == 201:
            print(f"   -> layer {layer_resp.json()['data']['id']} status={layer_resp.json()['data']['status']}")
        else:
            print(f"   -> layer upload failed: {layer_resp.text}")

        features_resp = await client.get(
            f"/api/v1/habitations/{habitation_id}/features", headers=auth_headers
        )
        feature_count = len(features_resp.json()["data"]["features"])
        print(f"   -> {feature_count} feature(s) now stored and spatially contained")

        print("\nDemo complete.")


if __name__ == "__main__":
    asyncio.run(main())