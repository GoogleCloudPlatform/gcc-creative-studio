from fastapi import APIRouter, Depends, HTTPException, status
from src.auth.auth_guard import get_current_user
from src.users.user_model import UserModel
from src.projects.project_repository import StoryboardRepository
from src.projects.dto.project_dto import StoryboardCreate, StoryboardUpdate, StoryboardResponse, StoryboardCreateResponse

router = APIRouter(
    prefix="/api/storyboards",
    tags=["Storyboards"],
)

@router.post("/", response_model=StoryboardCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_storyboard(
    storyboard_create: StoryboardCreate,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends()
):
    data = storyboard_create.model_dump()
    data["user_id"] = current_user.id
    
    storyboard = await storyboard_repo.create(data)
    return storyboard

@router.get("/{storyboard_id}", response_model=StoryboardResponse)
async def get_storyboard(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends()
):
    storyboard = await storyboard_repo.get_by_id_with_details(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this storyboard")
    return storyboard

@router.get("/", response_model=list[StoryboardResponse])
async def list_storyboards(
    workspace_id: int,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends()
):
    storyboards = await storyboard_repo.find_by_workspace(workspace_id)
    return storyboards

@router.put("/{storyboard_id}", response_model=StoryboardResponse)
async def update_storyboard(
    storyboard_id: int,
    storyboard_update: StoryboardUpdate,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends()
):
    storyboard = await storyboard_repo.get_by_id_with_details(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this storyboard")
        
    if storyboard_update.template_name is not None:
         await storyboard_repo.update(storyboard_id, {"template_name": storyboard_update.template_name})

    if storyboard_update.scenes is not None or storyboard_update.timeline_data is not None:
         updated_storyboard = await storyboard_repo.update_storyboard_data(
             storyboard_id=storyboard_id,
             storyboard_data={"scenes": storyboard_update.scenes} if storyboard_update.scenes else None,
             timeline_data=storyboard_update.timeline_data
         )
         return updated_storyboard

    return await storyboard_repo.get_by_id_with_details(storyboard_id)

@router.delete("/{storyboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storyboard(
    storyboard_id: int,
    current_user: UserModel = Depends(get_current_user),
    storyboard_repo: StoryboardRepository = Depends()
):
    storyboard = await storyboard_repo.get_by_id(storyboard_id)
    if not storyboard:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    if storyboard.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this storyboard")
        
    await storyboard_repo.delete(storyboard_id)
    return None
