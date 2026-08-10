# `move` — basic policy for UAV movement 

Every UAV can move around the map.
This policy governs that movement.
There are parameters that change how a UAV moves that should be set when this policy is applied to a UAV.

Most UAV policies inherits this policy so that UAVs can fly correctly.

Inherited obligations: see [`_contract.md`](_contract.md).

## POL-MOV-XX - Selecting Trajectories 

> For each movement action, an ego UAV must select a trajectory consisting of a direction (within configured directions)
> and a speed (within the configured speeds and as constrained by the policy parameters).

## POL-MOV-XX - Tunable Max Speed

> The policy shall define a maximum speed the ego UAV may select for each trajectory it selects;
> the maximum may depend on conditions such as the load carried by the UAV, its observed position on the
> map, the proximity to other UAVs, proximity of the base, or proximty of fire.

## POL-MOV-1 — Move to open cells

> For each movement action, an ego UAV following the `move` policy shall select trajectories (direction and speed)
> such that it completes its motion on an empty cell.

## POL-MOV-2 - Move through open paths

> For each movement action, an ego UAV following the `move` policy shall select trajectories (direction and speed)
> such that the ego UAV's path does not include cells occupied by other UAVs. 

## POL-MOV-XX - Maintain soft clearance from other UAVs

> For each movement action, an ego UAV shall select trajectories that avoid positioning the ego UAV within
> 

## POL-MOV-XX - Return to Base

> TODO

