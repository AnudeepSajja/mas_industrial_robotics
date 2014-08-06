#!/usr/bin/python

import rospy
import smach
import smach_ros

# import of generic states
import mir_states.common.basic_states as gbs
import mir_states.common.navigation_states as gns
import mir_states.common.manipulation_states as gms
import mir_states.common.perception_states as gps
import mir_states.common.perception_mockup_util as perception_mockup_util

#import robocup specific states
import mir_states.robocup.basic_transportation_test_states as btts


################################################################
class sub_sm_go_and_pick(smach.StateMachine):
    def __init__(self, use_mockup=None):
        smach.StateMachine.__init__(self, outcomes=['pose_skipped_but_platform_limit_reached', 
                                                    'no_more_free_poses',
                                                    'no_more_free_poses_at_robot_platf',
                                                    'no_more_task_for_given_type'],
                                          input_keys=['base_pose_to_approach',
                                                      'desired_distance_to_workspace',
                                                      'found_objects',
                                                      'lasttask',
                                                      'move_arm_to',
                                                      'move_base_by',
                                                      'object_pose',
                                                      'object_to_be_adjust_to',
                                                      'object_to_grasp',
                                                      'objects_to_be_grasped',
                                                      'rear_platform_free_poses',
                                                      'rear_platform_occupied_poses',
                                                      'recognized_objects',
                                                      'source_visits',
                                                      'task_list',
                                                      'vscount'],
                                          output_keys=['base_pose_to_approach', 
                                                       'found_objects',
                                                       'lasttask',
                                                       'move_arm_to',
                                                       'move_base_by',
                                                       'object_to_be_adjust_to',
                                                       'object_to_grasp',
                                                       'objects_to_be_grasped',
                                                       'rear_platform_free_poses',
                                                       'rear_platform_occupied_poses',
                                                       'source_visits',
                                                       'task_list',
                                                       'vscount'])

        self.use_mockup = use_mockup

        with self:
            smach.StateMachine.add('SELECT_SOURCE_SUBTASK', btts.select_btt_subtask(type="source"),
                transitions={'task_selected': 'MOVE_TO_SOURCE_LOCATION',
                             'no_more_task_for_given_type': 'no_more_task_for_given_type'})

            smach.StateMachine.add('MOVE_TO_SOURCE_LOCATION', gns.approach_pose(),
                transitions={'succeeded': 'PREPARE_FOR_PERCEPTION',
                             'failed': 'MOVE_TO_SOURCE_LOCATION'})


            ### start of concurrent state(s)
            sm_con_prepare_for_perception = smach.Concurrence(outcomes=['succeeded', 'failed_to_adjust_base','concurrency_mapping_failure'],
                                       default_outcome='concurrency_mapping_failure',
                                       outcome_map={'succeeded': {'ADJUST_POSE_WRT_WORKSPACE_AT_SOURCE': 'succeeded',
                                                                  'MOVE_ARM_OUT_OF_VIEW_SAFE': 'succeeded'},
                                                    'failed_to_adjust_base': {'ADJUST_POSE_WRT_WORKSPACE_AT_SOURCE': 'failed'}})

            with sm_con_prepare_for_perception:
                sm_sub_move_arm_safe = smach.StateMachine(outcomes=['succeeded'])
                with sm_sub_move_arm_safe:
                    smach.StateMachine.add('ADD_WALLS_TO_PLANNING_SCENE', gms.update_static_elements_in_planning_scene("walls", "add"),
                        transitions={'succeeded':'MOVE_ARM_OUT_OF_VIEW'})

                    smach.StateMachine.add('MOVE_ARM_OUT_OF_VIEW', gms.move_arm('out_of_view'),
                        transitions={'succeeded':'succeeded',
                                     'failed':'MOVE_ARM_OUT_OF_VIEW'})


                smach.Concurrence.add('ADJUST_POSE_WRT_WORKSPACE_AT_SOURCE', gns.adjust_to_workspace(0.15))
                smach.Concurrence.add('MOVE_ARM_OUT_OF_VIEW_SAFE', sm_sub_move_arm_safe)

            smach.StateMachine.add('PREPARE_FOR_PERCEPTION', sm_con_prepare_for_perception, transitions={'succeeded': 'RECOGNIZE_OBJECTS',
                                                                                  'failed_to_adjust_base': 'MOVE_TO_SOURCE_LOCATION',
                                                                                  'concurrency_mapping_failure': 'PREPARE_FOR_PERCEPTION'})
            ### end of concurrent state(s)


            smach.StateMachine.add('RECOGNIZE_OBJECTS', gps.find_objects(retries=3, frame_id='/odom'),
                transitions={'objects_found':'SELECT_OBJECT_TO_BE_GRASPED',
                            'no_objects_found':'SHIFT_BASE_RANDOM'},
                remapping={'found_objects':'recognized_objects'})

            smach.StateMachine.add('SHIFT_BASE_RANDOM', gns.move_base_relative([0.0, 0.0, -0.03, 0.03, 0.0, 0.0]),
                transitions={'succeeded': 'RECOGNIZE_OBJECTS_LOOP',
                              'timeout': 'RECOGNIZE_OBJECTS_LOOP'})

            #FIXME: Is there a loop reset?
            smach.StateMachine.add('RECOGNIZE_OBJECTS_LOOP', gbs.loop_for(1),
                                      transitions={'loop': 'RECOGNIZE_OBJECTS',
                                                   #'continue': 'SHIFT_BASE_RANDOM'})  # For BMT
                                                   'continue': 'SKIP_SOURCE_POSE'})  # For BTT

            smach.StateMachine.add('SELECT_OBJECT_TO_BE_GRASPED', btts.select_object_to_be_grasped(),
                transitions={'obj_selected':'PREPARE_FOR_GRASPING',
                            'no_obj_selected':'SKIP_SOURCE_POSE',
                            'no_more_free_poses_at_robot_platf':'no_more_free_poses_at_robot_platf'})

            ### start of concurrent state(s)
            sm_con_prepare_for_grasping = smach.Concurrence(outcomes=['succeeded', 'tf_error_in_computing_base_shift','concurrency_mapping_failure'],
                                                            default_outcome='concurrency_mapping_failure',
                                                            outcome_map={'succeeded': {'ALIGN_BASE_WITH_OBJECT': 'succeeded',
                                                                                       'ADD_WALLS_TO_PLANNING_SCENE': 'succeeded'},
                                                                         'tf_error_in_computing_base_shift': {'ALIGN_BASE_WITH_OBJECT': 'tf_error_in_computing_base_shift'}},
                                                            input_keys=['object_to_grasp','move_base_by'],
                                                            output_keys=['move_base_by'])

            with sm_con_prepare_for_grasping:
                sm_sub_shift_base = smach.StateMachine(outcomes=['succeeded', 'tf_error_in_computing_base_shift'],
                                                       input_keys=['object_to_grasp','move_base_by'],
                                                       output_keys=['move_base_by'])
                with sm_sub_shift_base:
                    smach.StateMachine.add('COMPUTE_BASE_SHIFT_TO_OBJECT', btts.compute_base_shift_to_object(),
                        transitions={'succeeded': 'MOVE_BASE_RELATIVE',
                                     'tf_error': 'tf_error_in_computing_base_shift'},
                        remapping={'object_pose': 'object_to_grasp'})

                    smach.StateMachine.add('MOVE_BASE_RELATIVE', gns.move_base_relative(),
                        transitions={'succeeded': 'succeeded',
                                     'timeout': 'MOVE_BASE_RELATIVE'})

                smach.Concurrence.add('ALIGN_BASE_WITH_OBJECT', sm_sub_shift_base)
                smach.Concurrence.add('ADD_WALLS_TO_PLANNING_SCENE', gms.update_static_elements_in_planning_scene("walls", "add"))

            smach.StateMachine.add('PREPARE_FOR_GRASPING', sm_con_prepare_for_grasping,
                transitions={'succeeded': 'MOVE_ARM_TO_PREGRASP',
                             'tf_error_in_computing_base_shift': 'PREPARE_FOR_PERCEPTION',
                             'concurrency_mapping_failure': 'PREPARE_FOR_GRASPING'})
            ### end of concurrent state(s)

            smach.StateMachine.add('MOVE_ARM_TO_PREGRASP', gms.move_arm("pre_grasp"),
                transitions={'succeeded': 'DO_VISUAL_SERVERING',
                             'failed': 'MOVE_ARM_TO_PREGRASP'})

            # state skipped
            smach.StateMachine.add('DO_VISUAL_SERVERING', gps.do_visual_servoing(),
                transitions={'succeeded':'GRASP_OBJ',
                            'failed':'VISUAL_SERVOING_LOOP',
                            'timeout':'VISUAL_SERVOING_LOOP',
                            'lost_object': 'VISUAL_SERVOING_LOOP'})
 
            smach.StateMachine.add('VISUAL_SERVOING_LOOP', btts.loop_for(max_loop_count=1),
                                      transitions={'loop': 'HELP_VISUAL_SERVOING',
                                                   'continue': 'SKIP_SOURCE_POSE'})
 
            smach.StateMachine.add('HELP_VISUAL_SERVOING', gns.adjust_to_workspace(0.12),
                transitions={'succeeded':'MOVE_ARM_TO_PREGRASP',
                             'failed':'MOVE_ARM_TO_PREGRASP'})

            if (self.use_mockup):
                    smach.StateMachine.add('GRASP_OBJ', gms.grasp_object(),
                        transitions={'succeeded':'ATTACH_OBJECT_TO_ROBOT',
                                     'failed':'SKIP_SOURCE_POSE'})

                    smach.StateMachine.add('ATTACH_OBJECT_TO_ROBOT', gms.update_robot_planning_scene("attach"),
                        transitions={'succeeded':'REMOVE_OBJECT_FROM_MOCKUP'},
                        remapping={'object': 'object_to_grasp'})

                    smach.StateMachine.add("REMOVE_OBJECT_FROM_MOCKUP",
                                           perception_mockup_util.remove_object_to_grasp_state(),
                                           transitions={'success':'PLACE_OBJ_ON_REAR_PLATFORM'})
            else:
                    smach.StateMachine.add('GRASP_OBJ', gms.grasp_object(),
                        transitions={'succeeded':'ATTACH_OBJECT_TO_ROBOT',
                                     'failed':'SKIP_SOURCE_POSE'})

                    smach.StateMachine.add('ATTACH_OBJECT_TO_ROBOT', gms.update_robot_planning_scene("attach"),
                        transitions={'succeeded':'PLACE_OBJ_ON_REAR_PLATFORM'},
                        remapping={'object': 'object_to_grasp'})

            smach.StateMachine.add('PLACE_OBJ_ON_REAR_PLATFORM', btts.place_obj_on_rear_platform_btt(),
                transitions={'succeeded':'DETACH_OBJECT_FROM_ROBOT',
                             'no_more_free_poses':'no_more_free_poses'})

            smach.StateMachine.add('DETACH_OBJECT_FROM_ROBOT', gms.update_robot_planning_scene("load"),
                transitions={'succeeded':'SELECT_OBJECT_TO_BE_GRASPED'},
                remapping={'object': 'object_to_grasp'})

            # MISC STATES
            smach.StateMachine.add('SKIP_SOURCE_POSE', btts.skip_pose('source'),
                transitions={'pose_skipped':'SELECT_SOURCE_SUBTASK',
                             'pose_skipped_but_platform_limit_reached':'pose_skipped_but_platform_limit_reached'})
 

 

################################################################
class sub_sm_go_to_destination(smach.StateMachine):
    def __init__(self):
        smach.StateMachine.__init__(self, outcomes=['destination_reached', 
                                                    'overall_done'],
                                          input_keys=['base_pose_to_approach',
                                                      'desired_distance_to_workspace',
                                                      'objects_goal_configuration',
                                                      'objects_to_be_grasped',
                                                      'rear_platform_occupied_poses',
                                                      'task_list'],
                                          output_keys=['base_pose_to_approach',
                                                       'objects_goal_configuration',
                                                       'objects_to_be_grasped',
                                                       'rear_platform_occupied_poses',
                                                       'task_list'])

        with self:
            smach.StateMachine.add('REMOVE_WALLS_FROM_PLANNING_SCENE', gms.update_static_elements_in_planning_scene("walls", "remove"),
                transitions={'succeeded':'SELECT_DELIVER_WORKSTATION'})

            smach.StateMachine.add('SELECT_DELIVER_WORKSTATION', btts.select_delivery_workstation(),
                transitions={'success':'MOVE_TO_DESTINATION_LOCATION',
                             'no_more_dest_tasks':'MOVE_TO_EXIT'})

            smach.StateMachine.add('MOVE_TO_DESTINATION_LOCATION', gns.approach_pose(),
                transitions={'succeeded':'ADJUST_POSE_WRT_WORKSPACE_AT_DESTINATION',
                             'failed':'MOVE_TO_DESTINATION_LOCATION'})

            smach.StateMachine.add('ADJUST_POSE_WRT_WORKSPACE_AT_DESTINATION', gns.adjust_to_workspace(0.12),
                transitions={'succeeded':'destination_reached',
                             'failed':'MOVE_TO_DESTINATION_LOCATION'})

            smach.StateMachine.add('MOVE_TO_EXIT', gns.approach_pose("EXIT"),
                transitions={'succeeded':'overall_done',
                             'failed':'MOVE_TO_EXIT'})


################################################################
class sub_sm_place(smach.StateMachine):
    def __init__(self):
        smach.StateMachine.__init__(self, outcomes=['succeeded', 
                                                    'no_more_obj_for_this_workspace'],
                                          input_keys=['base_pose_to_approach',
                                                      'destinaton_free_poses',
                                                      'last_grasped_obj',
                                                      'move_arm_to',
                                                      'obj_goal_configuration_poses',
                                                      'objects_goal_configuration',
                                                      'rear_platform_free_poses',
                                                      'rear_platform_occupied_poses',
                                                      'task_list'],
                                          output_keys=['base_pose_to_approach',
                                                      'destinaton_free_poses',
                                                      'last_grasped_obj',
                                                      'objects_goal_configuration',
                                                      'rear_platform_free_poses',
                                                      'rear_platform_occupied_poses',
                                                      'task_list'])

        with self:
            smach.StateMachine.add('ADD_WALLS_TO_PLANNING_SCENE', gms.update_static_elements_in_planning_scene("walls", "add"),
                transitions={'succeeded':'GRASP_OBJECT_FROM_PLTF'})

            smach.StateMachine.add('GRASP_OBJECT_FROM_PLTF', btts.grasp_obj_from_pltf_btt(),
                transitions={'object_grasped':'REATTACH_OBJECT_TO_ROBOT',
                             'no_more_obj_for_this_workspace':'REMOVE_WALLS_FROM_PLANNING_SCENE'})

            smach.StateMachine.add('REATTACH_OBJECT_TO_ROBOT', gms.update_robot_planning_scene("unload"),
                transitions={'succeeded':'MOVE_TO_INTERMEDIATE_POSE'},
                remapping={'object': 'last_grasped_obj'})

            smach.StateMachine.add('MOVE_TO_INTERMEDIATE_POSE', gms.move_arm('platform_intermediate'),
                transitions={'succeeded':'PLACE_OBJ_IN_CONFIGURATION',
                             'failed':'MOVE_TO_INTERMEDIATE_POSE'})

            smach.StateMachine.add('PLACE_OBJ_IN_CONFIGURATION', btts.place_object_in_configuration_btt(),
                transitions={'succeeded':'DELETE_OBJECT_FROM_ROBOT_1',
                             'no_more_cfg_poses':'DELETE_OBJECT_FROM_ROBOT_2'})

            smach.StateMachine.add('DELETE_OBJECT_FROM_ROBOT_1', gms.update_robot_planning_scene("detach"),
                transitions={'succeeded':'GRASP_OBJECT_FROM_PLTF'},
                remapping={'object': 'last_grasped_obj'})

            smach.StateMachine.add('DELETE_OBJECT_FROM_ROBOT_2', gms.update_robot_planning_scene("detach"),
                transitions={'succeeded':'MOVE_ARM_INSIDE_BASE_BOUNDARIES'},
                remapping={'object': 'object_to_grasp'})

            #smach.StateMachine.add('AVOID_WALLS_PRE_3', gms.move_arm('candle'),
            #    transitions={'succeeded': 'MOVE_ARM_INSIDE_BASE_BOUNDARIES',
            #                 'failed': 'AVOID_WALLS_PRE_3'})

            smach.StateMachine.add('MOVE_ARM_INSIDE_BASE_BOUNDARIES', gms.move_arm('platform_intermediate'),
                transitions={'succeeded':'succeeded',
                             'failed':'MOVE_ARM_INSIDE_BASE_BOUNDARIES'})

            smach.StateMachine.add('REMOVE_WALLS_FROM_PLANNING_SCENE', gms.update_static_elements_in_planning_scene("walls", "remove"),
                transitions={'succeeded':'no_more_obj_for_this_workspace'})


