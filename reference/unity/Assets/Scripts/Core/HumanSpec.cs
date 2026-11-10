namespace PoRace {

public enum Human { Matt, Grandma }

/// <summary>One human racer's contract as data, from its generated spec (MattSpec / GrandmaSpec, written by
/// training/matt/model_info.py). Both bodies use the G1 joint layout (29 joints, 103 obs), so MattController,
/// MattSkin and the race code run either one; every MuJoCo name of a body is Prefix + the trainer's name (Grandma
/// "gm_", Matt none), so both can share the race's single model. Each keeps its own policy (no shared brain).</summary>
public sealed class HumanSpec {
  public string Name, Prefix;
  public int Nu, Decimation, ObsDim;
  public float SimDt, ActionScale, GaitHz, GaitHzSlope, GaitHzV0, HomeHeight, PelvisRestZ, ImpRatio, FallenPelvisZ, MaxVx;
  public double Mass;
  public string[] Joints;
  public float[] DefaultPose, Kp, ForceMax;

  /// <summary>The MuJoCo name of `trainerName` on this body.</summary>
  public string N(string trainerName) => Prefix + trainerName;

  public static readonly HumanSpec Matt = new HumanSpec {
    Name = "Matt", Prefix = MattSpec.Prefix, Nu = MattSpec.Nu, Decimation = MattSpec.Decimation, ObsDim = MattSpec.ObsDim,
    SimDt = MattSpec.SimDt, ActionScale = MattSpec.ActionScale, GaitHz = MattSpec.GaitHz, GaitHzSlope = MattSpec.GaitHzSlope,
    GaitHzV0 = MattSpec.GaitHzV0, HomeHeight = MattSpec.HomeHeight, PelvisRestZ = MattSpec.PelvisRestZ, ImpRatio = MattSpec.ImpRatio,
    FallenPelvisZ = MattSpec.FallenPelvisZ, MaxVx = MattSpec.MaxVx, Mass = MattSpec.Mass, Joints = MattSpec.Joints,
    DefaultPose = MattSpec.DefaultPose, Kp = MattSpec.Kp, ForceMax = MattSpec.ForceMax };

  public static readonly HumanSpec Grandma = new HumanSpec {
    Name = "Grandma", Prefix = GrandmaSpec.Prefix, Nu = GrandmaSpec.Nu, Decimation = GrandmaSpec.Decimation, ObsDim = GrandmaSpec.ObsDim,
    SimDt = GrandmaSpec.SimDt, ActionScale = GrandmaSpec.ActionScale, GaitHz = GrandmaSpec.GaitHz, GaitHzSlope = GrandmaSpec.GaitHzSlope,
    GaitHzV0 = GrandmaSpec.GaitHzV0, HomeHeight = GrandmaSpec.HomeHeight, PelvisRestZ = GrandmaSpec.PelvisRestZ, ImpRatio = GrandmaSpec.ImpRatio,
    FallenPelvisZ = GrandmaSpec.FallenPelvisZ, MaxVx = GrandmaSpec.MaxVx, Mass = GrandmaSpec.Mass, Joints = GrandmaSpec.Joints,
    DefaultPose = GrandmaSpec.DefaultPose, Kp = GrandmaSpec.Kp, ForceMax = GrandmaSpec.ForceMax };

  public static HumanSpec Of(Human h) => h == Human.Grandma ? Grandma : Matt;
}

}
