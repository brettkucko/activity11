import os

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

# --- MongoDB connection (credentials come from .env / Render environment) ---
load_dotenv()
client = MongoClient(os.environ["MONGODB_URI"])
db = client["MobileApp"]
collection = db["sculptures"]

# --- FastAPI app setup ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic model: nonblank text fields + valid HTTP/HTTPS image URL ---
class SculptureValidated(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    description: str = Field(min_length=1)
    imageUrl: HttpUrl
    alt: str = Field(min_length=1)


@app.get("/hello")
def read_root():
    return {"message": "Hello from FastAPI + MongoDB Atlas backend!"}


# --- Read all sculptures ---
@app.get("/sculptures")
def get_sculptures():
    try:
        if "sculptures" not in db.list_collection_names():
            raise HTTPException(status_code=404, detail="Collection 'sculptures' not found")

        sculptures = list(collection.find())
        for s in sculptures:
            s["_id"] = str(s["_id"])  # ObjectId -> string
        return sculptures

    except HTTPException:
        raise
    except PyMongoError as e:
        print("Database error:", e)
        raise HTTPException(status_code=503, detail="Database not reachable")
    except Exception as e:
        print("Unexpected error:", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# --- Add a sculpture ---
@app.post("/sculptures", status_code=status.HTTP_201_CREATED)
def add_sculpture(sculpture: SculptureValidated):
    try:
        if "sculptures" not in db.list_collection_names():
            raise HTTPException(status_code=404, detail="Collection 'sculptures' not found")
        if collection.find_one({"name": sculpture.name}):
            raise HTTPException(status_code=409, detail="Sculpture already exists")

        # JSON mode converts HttpUrl to a MongoDB-compatible string.
        result = collection.insert_one(sculpture.model_dump(mode="json"))
        return {"message": "Sculpture added successfully", "id": str(result.inserted_id)}

    except HTTPException:
        raise
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Sculpture already exists")
    except PyMongoError as e:
        print("Database error:", e)
        raise HTTPException(status_code=503, detail="Database not reachable")
    except Exception as e:
        print("Unexpected error:", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# --- Update a sculpture by its current name ---
@app.put("/sculptures/{name}")
def update_sculpture(sculpture: SculptureValidated, name: str = Path(min_length=1)):
    try:
        if not name.strip():
            raise HTTPException(status_code=422, detail="Sculpture name cannot be blank")
        if "sculptures" not in db.list_collection_names():
            raise HTTPException(status_code=404, detail="Collection 'sculptures' not found")

        existing = collection.find_one({"name": name})
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Sculpture '{name}' not found")

        # Prevent renaming it to another sculpture's name.
        duplicate = collection.find_one({
            "name": sculpture.name,
            "_id": {"$ne": existing["_id"]},
        })
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Another sculpture already has that name")

        updated_data = sculpture.model_dump(mode="json")
        result = collection.update_one({"_id": existing["_id"]}, {"$set": updated_data})

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Sculpture no longer exists")
        if result.modified_count == 0:
            return {
                "message": "No changes needed; sculpture already has these values",
                "id": str(existing["_id"]),
            }
        return {"message": "Sculpture updated successfully", "id": str(existing["_id"])}

    except HTTPException:
        raise
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Another sculpture already has that name")
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


# --- Delete a sculpture by MongoDB _id ---
@app.delete("/sculptures/{sculpture_id}")
def delete_sculpture(
    # Must be a 24-character hex string, otherwise FastAPI returns 422.
    sculpture_id: str = Path(pattern=r"^[0-9a-fA-F]{24}$"),
):
    try:
        if "sculptures" not in db.list_collection_names():
            raise HTTPException(status_code=404, detail="Collection 'sculptures' not found")

        object_id = ObjectId(sculpture_id)
        existing = collection.find_one({"_id": object_id})
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Sculpture not found. It may have already been deleted",
            )

        result = collection.delete_one({"_id": object_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Sculpture no longer exists")

        return {
            "message": f"Sculpture '{existing.get('name', '')}' deleted successfully",
            "id": sculpture_id,
        }

    except HTTPException:
        raise
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database operation failed")
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
